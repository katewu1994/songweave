import json
from argparse import Namespace

import pytest

from music_vector_map.export.build import build_export
from music_vector_map.export.validate import validate_export_dir
from music_vector_map.interpretations import jobs
from music_vector_map.interpretations.cache import find, set_review
from music_vector_map.interpretations.checks import check_output, quote_flags
from music_vector_map.interpretations.client import Completion, MetaApiError, MetaClient, read_api_key, refuse_training_models
from music_vector_map.interpretations.payload import build_lyrics_payload, build_pair_payload


@pytest.fixture
def exported(fixture_cfg):
    # Test the enabled API path independently of the owner's local pause setting.
    fixture_cfg.data["meta_api"]["enabled"] = True
    build_export(fixture_cfg, log=lambda _: None)
    return fixture_cfg, json.loads((fixture_cfg.export_dir / "export.json").read_text(encoding="utf-8"))


def test_disabled_generation_never_reads_key_or_calls_api(exported, monkeypatch):
    cfg, _ = exported
    cfg.data["meta_api"]["enabled"] = False
    monkeypatch.setattr(jobs, "read_api_key", lambda *a: pytest.fail("credentials read while disabled"))
    assert jobs.run_generate(cfg, _args(pairs="t_fix0:t_fix1")) == 2


@pytest.mark.parametrize(
    "prompt,args",
    [
        ("PAIR_EXPLANATION.md", {"pairs": "t_fix0:t_fix1"}),
        ("LYRIC_UNDERSTANDING.md", {"task": "understand-lyrics", "tracks": "t_fix0", "allow_lyrics_upload": True}),
    ],
)
def test_missing_local_prompt_blocks_generation(exported, monkeypatch, capsys, prompt, args):
    cfg, _ = exported
    (cfg.root / "prompts" / prompt).unlink()
    monkeypatch.setattr(jobs, "read_api_key", lambda *a: pytest.fail("credentials read without prompt"))
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a: pytest.fail("API called without prompt"))
    assert jobs.run_generate(cfg, _args(**args)) == 1
    assert "Generation unavailable" in capsys.readouterr().err


def test_local_translation_provenance_and_stale_source(exported, monkeypatch):
    from copy import deepcopy
    from music_vector_map.export.build import write_interpretations
    from music_vector_map.interpretations.cache import save
    from music_vector_map.interpretations.translations import output_hash

    cfg, data = exported
    _, allowed = build_pair_payload(data, "t_fix0", "t_fix1", False)
    rel = next(a for a in allowed if a.startswith("rel:rhythm_merit"))
    exc = next(a for a in allowed if a.startswith("exc:rhythm_merit"))
    out = _pair_output(rel, exc)
    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a: Completion(json.dumps(out), "stop", "fixture", "fixture-model", {}, 0.01))
    assert jobs.run_generate(cfg, _args(pairs="t_fix0:t_fix1", lang="en")) == 0
    items = json.loads((cfg.export_dir / "interpretations.json").read_text())["items"]
    source = items[0]
    translated = deepcopy(out)
    translated["summary"] = "テスト用の日本語。"
    translated["similarities"][0]["statement"] = "テスト用の観察。"
    record = {"source_interpretation_id": source["interpretation_id"], "source_output_sha256": output_hash(out), "language": "ja", "output": translated}
    folder = cfg.interpretations_dir / "translations"
    folder.mkdir()
    path = folder / "fixture_ja.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a: pytest.fail("network during local export"))
    write_interpretations(cfg)
    result = json.loads((cfg.export_dir / "interpretations.json").read_text())
    assert len(result["items"]) == 2 and result["failed_validation_count"] == 0
    assert result["items"][1]["generation"] == "local_translation"
    assert result["items"][1]["prompt"]["output_language"] == "ja"
    assert result["items"][0] == source
    assert find(cfg, source["interpretation_id"])["output"] == out
    assert validate_export_dir(cfg.export_dir)[0] == []

    # A citation substitution and a source hash change each invalidate the translation.
    translated["similarities"][0]["evidence_ids"] = [exc]
    path.write_text(json.dumps(record))
    write_interpretations(cfg)
    result = json.loads((cfg.export_dir / "interpretations.json").read_text())
    assert len(result["items"]) == 1 and result["failed_validation_count"] == 1
    record["output"] = deepcopy(out)
    record["source_output_sha256"] = "stale"
    path.write_text(json.dumps(record))
    write_interpretations(cfg)
    assert json.loads((cfg.export_dir / "interpretations.json").read_text())["failed_validation_count"] == 1

    # An actual Japanese response wins; the sidecar cannot impersonate or replace it.
    record["source_output_sha256"] = output_hash(out)
    path.write_text(json.dumps(record))
    native = find(cfg, source["interpretation_id"])
    native["interpretation_id"] += ":fixture-ja"
    native["prompt"]["output_language"] = "ja"
    save(cfg, native)
    write_interpretations(cfg)
    result = json.loads((cfg.export_dir / "interpretations.json").read_text())
    assert len(result["items"]) == 2
    assert all(i["generation"] == "cached_real_api_response" for i in result["items"])


def test_pair_payload_scope_without_lyrics_permission(exported):
    cfg, data = exported
    payload, allowed = build_pair_payload(data, "t_fix1", "t_fix0", allow_lyrics=False)
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["audio_sent"] is False and payload["titles_sent"] is False
    assert "Fixture 0" not in text and "line one" not in text and str(cfg.root) not in text
    assert "lyrics_sonar" not in [d["view_id"] for d in payload["dimensions"]]
    assert not any(a.startswith(("lyr:", "lpair:")) for a in allowed)
    assert payload["tracks"] == {"A": "t_fix0", "B": "t_fix1"}  # canonical order
    assert "t_fix2" not in text  # unrelated tracks are not sent


def test_pair_payload_with_lyrics_permission(exported):
    _, data = exported
    payload, allowed = build_pair_payload(data, "t_fix0", "t_fix1", allow_lyrics=True)
    assert payload["lyrics"]["sent"] is True
    assert any(a.startswith("lyr:") for a in allowed)


def test_lyrics_payload_requires_available_text(exported):
    _, data = exported
    payload, allowed = build_lyrics_payload(data, "t_fix0")
    assert allowed == {"lyr:t_fix0:0", "lyr:t_fix0:1"}
    with pytest.raises(ValueError):
        build_lyrics_payload(data, "t_fix2")


def _pair_output(eid_rel, eid_exc):
    return {
        "summary": "s",
        "similarities": [{"dimension": "rhythm_merit", "statement": "x", "evidence_ids": [eid_rel]}],
        "differences": [],
        "listening_guide": [{"evidence_id": eid_exc, "suggestion": "listen"}],
        "uncertainties": ["u"],
    }


def test_check_output_citations_and_lint():
    allowed = {"rel:rhythm_merit:a:b", "exc:rhythm_merit:a:b:0", "rel:overall_peav:a:b"}
    ok = check_output("pair_explanation", _pair_output("rel:rhythm_merit:a:b", "exc:rhythm_merit:a:b:0"), allowed)
    assert ok["status"] == "pass" and ok["lint_flags"] == []
    bad = check_output("pair_explanation", _pair_output("rel:fake", "exc:rhythm_merit:a:b:0"), allowed)
    assert bad["status"] == "fail"
    out = _pair_output("rel:overall_peav:a:b", "exc:rhythm_merit:a:b:0")
    out["similarities"][0]["statement"] = "两首都用钢琴，120 BPM"
    flagged = check_output("pair_explanation", out, allowed)
    assert flagged["status"] == "pass"
    assert {f["flag"] for f in flagged["lint_flags"]} >= {"instrument", "tempo_number", "dimension_mismatch"}
    assert check_output("pair_explanation", {"summary": "x"}, allowed)["status"] == "fail"
    times = {"exc:rhythm_merit:a:b:0": {"00:30.00-01:00.00", "01:00.00-01:30.00"}}
    out = _pair_output("rel:rhythm_merit:a:b", "exc:rhythm_merit:a:b:0")
    out["listening_guide"][0]["suggestion"] = "比较 00:30.00-01:00.00 与 02:00.00-02:30.00"
    tf = check_output("pair_explanation", out, allowed, times)["lint_flags"]
    assert [f["detail"] for f in tf if f["flag"] == "time_not_in_cited_evidence"] == ["02:00.00-02:30.00"]


def test_quote_check_tolerates_old_kana_but_flags_inventions():
    lyrics = {"lyr:t:0": "ねえ、待つてゐたんだよ\n留めてゐるまゝの生命"}
    ok = {"overview": "「待っていた」と「留めているままの生命」", "observations": []}
    assert quote_flags(ok, lyrics) == []
    bad = {"overview": "「明日また会おう」", "observations": []}
    assert [f["detail"] for f in quote_flags(bad, lyrics)] == ["明日また会おう"]


def test_contributor_models_refused():
    with pytest.raises(MetaApiError):
        refuse_training_models("muse-spark-1.3-contributor")
    with pytest.raises(MetaApiError):
        MetaClient("https://api.meta.ai/v1", "k", "muse-spark-1.3-contributor")


def test_read_api_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    (tmp_path / ".env").write_text("# c\nMETA_API_KEY='abc123'\n")
    assert read_api_key(tmp_path, ["META_API_KEY", "MODEL_API_KEY"]) == "abc123"


def _args(**kw):
    base = dict(task="explain", pairs=None, tracks=None, allow_lyrics_upload=False, dry_run=False, max_items=None, force=False, model=None, lang=None, all_pairs=False, workers=1)
    base.update(kw)
    return Namespace(**base)


def test_generation_blocks_without_permission_and_cap(exported, monkeypatch):
    cfg, _ = exported
    called = []
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: called.append(1))
    assert jobs.run_generate(cfg, _args(task="understand-lyrics", tracks="t_fix0")) == 2
    pairs = ",".join(f"t_fix0:t_fix{i}" for i in (1, 2, 3)) + ",t_fix1:t_fix2,t_fix1:t_fix3,t_fix2:t_fix3,t_fix0:t_fix1"
    assert jobs.run_generate(cfg, _args(pairs=pairs)) == 2
    assert jobs.run_generate(cfg, _args(pairs="t_fix0:t_fix1", model="muse-spark-1.3-contributor")) == 2
    assert called == []


def test_dry_run_sends_nothing(exported, monkeypatch):
    cfg, _ = exported
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: pytest.fail("network call in dry run"))
    assert jobs.run_generate(cfg, _args(pairs="t_fix0:t_fix1", dry_run=True)) == 0
    assert list((cfg.interpretations_dir / "dryrun").glob("*.json"))


def test_generate_cache_validate_review_export(exported, monkeypatch):
    cfg, data = exported
    payload, allowed = build_pair_payload(data, "t_fix0", "t_fix1", allow_lyrics=False)
    rel = next(a for a in allowed if a.startswith("rel:rhythm_merit"))
    exc = next(a for a in allowed if a.startswith("exc:rhythm_merit"))
    content = json.dumps(_pair_output(rel, exc))
    calls = []

    def fake(self, system, user, name, schema):
        calls.append(user)
        assert "No audio was sent" in system
        return Completion(content=content, finish_reason="stop", response_id="r1", model="muse-spark-1.3", usage={}, latency_seconds=0.1)

    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setattr(MetaClient, "chat_json", fake)
    assert jobs.run_generate(cfg, _args(pairs="t_fix1:t_fix0")) == 0
    assert jobs.run_generate(cfg, _args(pairs="t_fix1:t_fix0")) == 0  # cached, no second call
    assert len(calls) == 1
    interp = json.loads((cfg.export_dir / "interpretations.json").read_text(encoding="utf-8"))
    item = interp["items"][0]
    assert item["review"]["status"] == "unreviewed" and item["generation"] == "cached_real_api_response"
    assert "payload" not in item
    assert validate_export_dir(cfg.export_dir)[0] == []
    rec = set_review(cfg, item["interpretation_id"], "approved", "owner", "checked by ear")
    assert find(cfg, item["interpretation_id"])["review"]["status"] == "approved" == rec["review"]["status"]


def test_invalid_citation_not_exported(exported, monkeypatch):
    cfg, _ = exported
    content = json.dumps(_pair_output("rel:invented", "exc:invented"))
    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setattr(MetaClient, "chat_json", lambda *a, **k: Completion(content, "stop", "r", "m", {}, 0.1))
    assert jobs.run_generate(cfg, _args(pairs="t_fix0:t_fix1")) == 1
    interp = json.loads((cfg.export_dir / "interpretations.json").read_text(encoding="utf-8"))
    assert interp["items"] == [] and interp["failed_validation_count"] == 1


def test_all_pairs_needs_explicit_cap_and_runs_in_parallel(exported, monkeypatch):
    cfg, data = exported

    def fake(self, system, user, name, schema):
        payload = json.loads(user)
        rel = next(d["relation"]["evidence_id"] for d in payload["dimensions"] if d["available"])
        out = {"summary": "s", "similarities": [{"dimension": rel.split(":")[1], "statement": "x", "evidence_ids": [rel]}], "differences": [], "listening_guide": [], "uncertainties": []}
        return Completion(json.dumps(out), "stop", "r", "muse-spark-1.3", {}, 0.01)

    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setattr(MetaClient, "chat_json", fake)
    assert jobs.run_generate(cfg, _args(all_pairs=True, max_items=2)) == 2  # never silently truncated
    assert jobs.run_generate(cfg, _args(all_pairs=True, max_items=len(data["pairs"]), workers=3)) == 0
    interp = json.loads((cfg.export_dir / "interpretations.json").read_text(encoding="utf-8"))
    assert len(interp["items"]) == len(data["pairs"])
