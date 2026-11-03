import http.client
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from music_vector_map.serve import make_handler


def test_range_requests_for_audio(tmp_path):
    dist = tmp_path / "dist"
    export = tmp_path / "export"
    (export / "media").mkdir(parents=True)
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    blob = bytes(range(256)) * 40
    (export / "media" / "t.mp3").write_bytes(blob)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(dist, export))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/data/media/t.mp3", headers={"Range": "bytes=100-199"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206
            assert r.headers["Content-Range"] == f"bytes 100-199/{len(blob)}"
            assert r.read() == blob[100:200]
        with urllib.request.urlopen(base + "/data/media/t.mp3") as r:
            assert r.status == 200 and r.read() == blob
        with urllib.request.urlopen(base + "/some/route") as r:  # SPA fallback
            assert b"app" in r.read()
        # Raw (un-normalised) traversal attempt must never leave the two served roots.
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        conn.request("GET", "/data/../../../../etc/passwd")
        body = conn.getresponse().read()
        assert b"root:" not in body
    finally:
        srv.shutdown()
