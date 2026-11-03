"""`mvm serve`: localhost-only static server for web/dist and the export bundle.

/            -> web/dist (built React app)
/data/...    -> artifacts/export (export.json, interpretations.json, media/)
/api/...     -> on-demand pair explanations (generate_api.py); POST only from this page's own origin
HTTP Range is supported so the browser can seek inside audio files.
"""

from __future__ import annotations

import json
import mimetypes
import posixpath
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("application/javascript", ".js")


def make_handler(dist: Path, export: Path, api=None):
    class Handler(SimpleHTTPRequestHandler):
        def _json(self, status: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _same_origin(self) -> bool:
            # Blocks other websites from driving paid API calls through this local server:
            # the custom header forces a CORS preflight (never answered), and Origin must be ours.
            if self.headers.get("X-SongWeave") != "1":
                return False
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            return origin is None or urllib.parse.urlsplit(origin).netloc == host

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path == "/api/status":
                if api is None:
                    return self._json(200, {"available": False})
                return self._json(200, api.status())
            return super().do_GET()

        def do_POST(self):
            from .generate_api import ApiError

            route = urllib.parse.urlsplit(self.path).path
            if api is None or route not in ("/api/generate/preview", "/api/generate"):
                return self._json(404, {"error": "not found"})
            if not self._same_origin():
                return self._json(403, {"error": "forbidden"})
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 10_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                result = api.preview(body) if route.endswith("preview") else api.generate(body)
                return self._json(200, result)
            except ApiError as e:
                return self._json(e.status, {"error": str(e)})
            except (ValueError, KeyError) as e:
                return self._json(400, {"error": str(e)})

        def translate_path(self, path: str) -> str:
            path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
            parts = [p for p in posixpath.normpath(path).split("/") if p and p not in (".", "..")]
            if parts[:1] == ["data"]:
                base, parts = export, parts[1:]
            else:
                base = dist
            target = base.joinpath(*parts) if parts else base
            if base is dist and not target.exists():
                target = dist / "index.html"  # single-page app fallback
            return str(target)

        def end_headers(self) -> None:
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def send_head(self):
            rng = self.headers.get("Range")
            path = Path(self.translate_path(self.path))
            if not rng or not path.is_file():
                return super().send_head()
            size = path.stat().st_size
            try:
                unit, spec = rng.split("=", 1)
                start_s, end_s = spec.split(",")[0].strip().split("-")
                if start_s == "":
                    start, end = max(0, size - int(end_s)), size - 1
                else:
                    start, end = int(start_s), (int(end_s) if end_s else size - 1)
                if unit != "bytes" or start > end or start >= size:
                    raise ValueError
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None
            end = min(end, size - 1)
            f = open(path, "rb")
            f.seek(start)
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self._remaining = end - start + 1
            return f

        def copyfile(self, source, outputfile) -> None:
            remaining = getattr(self, "_remaining", None)
            if remaining is None:
                return super().copyfile(source, outputfile)
            try:
                while remaining > 0:
                    chunk = source.read(min(1 << 16, remaining))
                    if not chunk:
                        break
                    outputfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self._remaining = None

        def log_message(self, fmt, *args) -> None:  # quieter: only errors
            if args and str(args[1]).startswith(("4", "5")):
                super().log_message(fmt, *args)

    return Handler


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("mvm serve binds to localhost only; opening public ports is out of scope")
    dist = cfg.root / "web" / "dist"
    if not (dist / "index.html").is_file():
        print("web/dist missing: serving /data only (use with `npm run dev`, or build with `npm run build`)")
    if not (cfg.export_dir / "export.json").is_file():
        raise SystemExit("no export; run `mvm export` first")
    from .generate_api import GenerateApi

    httpd = ThreadingHTTPServer((host, port), make_handler(dist, cfg.export_dir, GenerateApi(cfg)))
    print(f"SongWeave: http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
