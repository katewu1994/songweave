import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from music_vector_map.export.build import build_export
from music_vector_map.generate_api import GenerateApi
from music_vector_map.interpretations.client import Completion, MetaClient
from music_vector_map.serve import make_handler


@pytest.fixture
def server(fixture_cfg, tmp_path, monkeypatch):
    fixture_cfg.data["meta_api"]["enabled"] = True
    build_export(fixture_cfg, log=lambda _: None)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    monkeypatch.setenv("META_API_KEY", "test-key")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(dist, fixture_cfg.export_dir, GenerateApi(fixture_cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield fixture_cfg, srv.server_address[1]
    srv.shutdown()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    h = {"Content-Type": "application/json", "X-SongWeave": "1", "Origin": f"http://127.0.0.1:{port}"}
    h.update(headers or {})
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers={k: v for k, v in h.items() if v is not None})
    r = conn.getresponse()
    return r.status, json.loads(r.read() or b"null")


def test_status_does_not_expose_key(server):
    _, port = server
    status, body = call(port, "GET", "/api/status")
    assert status == 200 and body["available"] is True
    assert "test-key" not in json.dumps(body)


def test_missing_prompt_disables_generation_and_keeps_local_export(server, monkeypatch):
    from music_vector_map import generate_api
    from music_vector_map.export.validate import validate_export_dir

    cfg, port = server
    (cfg.root / "prompts" / "PAIR_EXPLANATION.md").unlink()
    monkeypatch.setattr(generate_api, "read_api_key", lambda *a: pytest.fail("credentials read without prompt"))
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a: pytest.fail("API called without prompt"))
    assert call(port, "GET", "/api/status")[1]["available"] is False
    body = {"a": "t_fix0", "b": "t_fix1", "confirm_job_id": "unavailable"}
    for path in ("/api/generate/preview", "/api/generate"):
        status, result = call(port, "POST", path, body)
        assert status == 503 and "Generation unavailable" in result["error"]
    assert call(port, "GET", "/data/export.json")[0] == 200
    assert validate_export_dir(cfg.export_dir)[0] == []


def test_disabled_api_is_unavailable_and_refuses_generation(server, monkeypatch):
    cfg, port = server
    cfg.data["meta_api"]["enabled"] = False
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a: pytest.fail("API called while paused"))
    assert call(port, "GET", "/api/status")[1]["available"] is False
    req = {"a": "t_fix0", "b": "t_fix1", "lang": "ja"}
    _, preview = call(port, "POST", "/api/generate/preview", req)
    req["confirm_job_id"] = preview["job_id"]
    assert call(port, "POST", "/api/generate", req)[0] == 503


def test_preview_sends_nothing_and_shows_scope(server, monkeypatch):
    _, port = server
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: pytest.fail("network call during preview"))
    status, body = call(port, "POST", "/api/generate/preview", {"a": "t_fix1", "b": "t_fix0", "lang": "ja"})
    assert status == 200 and body["cached"] is False
    assert body["scope"]["audio"] is False and body["scope"]["lyrics_text"] is False and body["scope"]["titles_or_artist"] is False


def test_cross_site_requests_refused(server, monkeypatch):
    _, port = server
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: pytest.fail("network call from a forbidden request"))
    req = {"a": "t_fix0", "b": "t_fix1"}
    assert call(port, "POST", "/api/generate", req, {"Origin": "https://evil.example"})[0] == 403
    assert call(port, "POST", "/api/generate", req, {"X-SongWeave": None})[0] == 403


def test_generate_requires_matching_confirmation(server, monkeypatch):
    cfg, port = server
    _, prev = call(port, "POST", "/api/generate/preview", {"a": "t_fix0", "b": "t_fix1", "lang": "en"})
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: pytest.fail("network call without confirmation"))
    assert call(port, "POST", "/api/generate", {"a": "t_fix0", "b": "t_fix1", "lang": "en", "confirm_job_id": "wrong"})[0] == 409

    def fake(self, system, user, name, schema):
        payload = json.loads(user)
        rel = next(d["relation"]["evidence_id"] for d in payload["dimensions"] if d["available"])
        out = {"summary": "s", "similarities": [{"dimension": rel.split(":")[1], "statement": "x", "evidence_ids": [rel]}], "differences": [], "listening_guide": [], "uncertainties": []}
        return Completion(json.dumps(out), "stop", "r", "muse-spark-1.3", {}, 0.01)

    monkeypatch.setattr(MetaClient, "chat_json", fake)
    status, body = call(port, "POST", "/api/generate", {"a": "t_fix0", "b": "t_fix1", "lang": "en", "confirm_job_id": prev["job_id"]})
    assert status == 200 and body["status"] == "ok" and body["interpretation_id"] == prev["job_id"]
    items = json.loads((cfg.export_dir / "interpretations.json").read_text(encoding="utf-8"))["items"]
    assert [i["interpretation_id"] for i in items] == [prev["job_id"]]
    assert call(port, "POST", "/api/generate/preview", {"a": "t_fix0", "b": "t_fix1", "lang": "en"})[1]["cached"] is True


def test_bad_input(server):
    _, port = server
    assert call(port, "POST", "/api/generate/preview", {"a": "t_fix0", "b": "t_fix0"})[0] == 400
    assert call(port, "POST", "/api/generate/preview", {"a": "t_fix0", "b": "nope"})[0] == 404
    assert call(port, "POST", "/api/generate/preview", {"a": "t_fix0", "b": "t_fix1", "lang": "fr"})[0] == 400
