"""Test fixtures. Everything here is FIXTURE data for software tests — never evidence of musical quality."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from music_vector_map.config import Config, load_config, stable_hash
from music_vector_map.schemas import MANIFEST_SCHEMA, MERIT_HEADS, VIEW_SPACE
from music_vector_map.store import write_record

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "songweave.toml", tmp_path / "config" / "songweave.toml")
    # Mocked generation tests must not depend on unpublished production prompts.
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ("PAIR_EXPLANATION.md", "LYRIC_UNDERSTANDING.md"):
        (prompts / name).write_text(
            "Prompt version: `fixture-only-v1`\n\n"
            "<!-- PROMPT START -->\n"
            "Fixture-only prompt. No audio was sent. Write in {output_language}.\n"
            "<!-- PROMPT END -->\n",
            encoding="utf-8",
        )
    return tmp_path


def _tone(path: Path, seconds: float, freq: float, sr: int = 16000, silent_tail: float = 0.0) -> None:
    t = np.arange(int(seconds * sr)) / sr
    x = 0.2 * np.sin(2 * np.pi * freq * t)
    if silent_tail:
        x[-int(silent_tail * sr) :] = 0
    sf.write(path, x.astype(np.float32), sr)


def write_fixture_dataset(root: Path, n: int = 4, lyrics_for: tuple[int, ...] = (0, 1), seed: int = 0) -> Config:
    """Fixture manifest + audio + synthetic analysis records (labelled kind=fixture)."""
    rng = np.random.default_rng(seed)
    data = root / "data"
    (data / "songs").mkdir(parents=True)
    (data / "lyrics").mkdir()
    tracks = []
    for i in range(n):
        name = f"fixture_{i}"
        _tone(data / "songs" / f"{name}.wav", 40.0 + 5 * i, 220.0 * (i + 1))
        lyr = {"status": "not_provided", "path": None, "lang": None}
        if i in lyrics_for:
            (data / "lyrics" / f"{name}.txt").write_text(f"line one {i}\nline two {i}\n\nsecond stanza {i}\n", encoding="utf-8")
            lyr = {"status": "available", "path": f"lyrics/{name}.txt", "lang": "eng_Latn"}
        tracks.append({"track_id": f"t_fix{i}", "title": f"Fixture {i}", "artist": "Fixture", "audio": f"songs/{name}.wav", "lyrics": lyr})
    (data / "manifest.json").write_text(
        json.dumps({"schema": MANIFEST_SCHEMA, "dataset": {"id": "fixture", "name": "Fixture set", "kind": "fixture"}, "tracks": tracks}),
        encoding="utf-8",
    )
    cfg = load_config(root / "config" / "songweave.toml")
    from music_vector_map.audio.windows import Window, plan_windows
    from music_vector_map.config import file_sha256

    for i, t in enumerate(tracks):
        audio = data / t["audio"]
        dur = sf.info(str(audio)).duration
        sha = file_sha256(audio)
        for view, win, hop, dim in (("overall_peav", 10.0, 10.0, 16), *((v, 30.0, 15.0, 8) for v in MERIT_HEADS)):
            spans = plan_windows(dur, win, hop)
            windows = [Window(index=k, start=a, end=b, rms_dbfs=-20.0, silent=False) for k, (a, b) in enumerate(spans)]
            settings = {"fixture": view, "window_seconds": win}
            emb = rng.normal(size=(len(windows), dim)) + (i % 2) * 2.0
            meta = {
                "view_id": view,
                "unit": "window",
                "input_sha256": sha,
                "duration_seconds": dur,
                "settings": settings,
                "settings_hash": stable_hash(settings),
                "model_info": {"fixture": True},
                "windows": [w.to_dict() for w in windows],
                "analyzed_unit_ids": [w.index for w in windows],
                "coverage": "full",
            }
            write_record(cfg.analysis_dir, VIEW_SPACE[view], t["track_id"], meta, [w.index for w in windows], emb)
        if t["lyrics"]["status"] == "available":
            blocks = [
                {"index": 0, "text": f"line one {i}\nline two {i}", "line_start": 1, "line_end": 2},
                {"index": 1, "text": f"second stanza {i}", "line_start": 4, "line_end": 4},
            ]
            settings = {"fixture": "sonar"}
            meta = {
                "view_id": "lyrics_sonar",
                "unit": "lyric_block",
                "input_sha256": "fixture",
                "settings": settings,
                "settings_hash": stable_hash(settings),
                "model_info": {"fixture": True},
                "blocks": blocks,
                "analyzed_unit_ids": [0, 1],
                "coverage": "full",
            }
            write_record(cfg.analysis_dir, "sonar_text", t["track_id"], meta, [0, 1], rng.normal(size=(2, 12)))
    return cfg


@pytest.fixture
def fixture_cfg(fixture_root: Path) -> Config:
    return write_fixture_dataset(fixture_root)
