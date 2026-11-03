import json

import pytest

from music_vector_map.export.build import build_export, build_export_data
from music_vector_map.export.validate import validate_export_data, validate_export_dir
from music_vector_map.manifest import load_manifest
from music_vector_map.store import read_meta, record_paths

from .conftest import write_fixture_dataset


def test_export_validates_and_marks_fixture(fixture_cfg):
    path = build_export(fixture_cfg, log=lambda _: None)
    errors, warns = validate_export_dir(path.parent)
    assert errors == []
    assert any("FIXTURE" in w for w in warns)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["dataset"]["kind"] == "fixture"
    assert (path.parent / data["tracks"][0]["media"]).is_file()


def test_missing_lyrics_is_unavailable_not_zero(fixture_cfg):
    data = build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)
    lyr = next(v for v in data["views"] if v["view_id"] == "lyrics_sonar")
    assert sorted(lyr["included"]) == ["t_fix0", "t_fix1"]
    assert {e["reason"] for e in lyr["excluded"]} == {"lyrics_not_provided"}
    rel = data["pairs"]["t_fix0|t_fix2"]["views"]["lyrics_sonar"]
    assert rel == {"available": False, "missing": ["t_fix2"]}
    rel2 = data["pairs"]["t_fix0|t_fix1"]["views"]["lyrics_sonar"]
    assert rel2["available"] and rel2["lyric_pairs"][0]["a"]["evidence_id"].startswith("lyr:t_fix0:")


def test_views_use_separate_spaces_and_excerpts_are_real_time(fixture_cfg):
    data = build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)
    spaces = {v["view_id"]: v["space"] for v in data["views"]}
    assert len(set(spaces.values())) == 5
    durs = {t["track_id"]: t["duration_seconds"] for t in data["tracks"]}
    for p in data["pairs"].values():
        for vid in ("overall_peav", "melody_merit", "rhythm_merit", "timbre_merit"):
            rel = p["views"][vid]
            for e in rel["excerpts"]:
                assert 0 <= e["a"]["start"] < e["a"]["end"] <= durs[e["a"]["track_id"]] + 1e-6
                assert e["id"].startswith(f"exc:{vid}:")
    assert validate_export_data(data)[0] == []


def test_partial_coverage_excluded_from_full_song_view(fixture_cfg):
    _, js = record_paths(fixture_cfg.analysis_dir, "merit_rhythm", "t_fix3")
    meta = read_meta(fixture_cfg.analysis_dir, "merit_rhythm", "t_fix3")
    meta["coverage"] = "partial"
    js.write_text(json.dumps(meta), encoding="utf-8")
    data = build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)
    rhythm = next(v for v in data["views"] if v["view_id"] == "rhythm_merit")
    assert "t_fix3" not in rhythm["included"]
    assert {"track_id": "t_fix3", "reason": "coverage_partial"} in rhythm["excluded"]
    melody = next(v for v in data["views"] if v["view_id"] == "melody_merit")
    assert "t_fix3" in melody["included"]


def test_mixed_settings_refused(fixture_cfg):
    _, js = record_paths(fixture_cfg.analysis_dir, "peav_audio", "t_fix1")
    meta = read_meta(fixture_cfg.analysis_dir, "peav_audio", "t_fix1")
    meta["settings_hash"] = "different"
    js.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RuntimeError, match="mixed preprocessing"):
        build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)


def test_validator_catches_score_on_missing_relation(fixture_cfg):
    data = build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)
    data["pairs"]["t_fix0|t_fix2"]["views"]["lyrics_sonar"]["score"] = 0.0
    errors, _ = validate_export_data(data)
    assert any("missing must not be zero" in e for e in errors)


def test_validator_catches_neighbour_order(fixture_cfg):
    data = build_export_data(fixture_cfg, load_manifest(fixture_cfg.manifest_path), log=lambda _: None)
    v = data["views"][0]
    first = next(iter(v["neighbors"]))
    v["neighbors"][first] = list(reversed(v["neighbors"][first]))
    assert any("not ordered" in e for e in validate_export_data(data)[0])


def test_more_tracks(fixture_root):
    cfg = write_fixture_dataset(fixture_root, n=6, lyrics_for=())
    data = build_export_data(cfg, load_manifest(cfg.manifest_path), log=lambda _: None)
    assert len(data["pairs"]) == 15
    lyr = next(v for v in data["views"] if v["view_id"] == "lyrics_sonar")
    assert lyr["status"] == "unavailable" and lyr["included"] == []
