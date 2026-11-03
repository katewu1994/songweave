import json

import numpy as np
import pytest

from music_vector_map.audio.windows import Window, coverage, mark_windows, plan_windows
from music_vector_map.lyrics.blocks import block_lang, split_blocks
from music_vector_map.manifest import ManifestError, init_manifest, load_manifest, make_track_id


@pytest.mark.parametrize("dur,win,hop", [(233.77, 10, 10), (233.77, 30, 15), (30.0, 30, 15), (95.5, 30, 15), (10.0, 10, 10)])
def test_windows_tile_whole_song_without_padding(dur, win, hop):
    spans = plan_windows(dur, win, hop)
    assert spans[0][0] == 0.0
    assert abs(spans[-1][1] - dur) < 1e-6
    for a, b in spans:
        assert 0 <= a < b <= dur + 1e-9
        assert b - a <= win + 1e-9
    # no gaps between consecutive windows
    for (a1, b1), (a2, _) in zip(spans, spans[1:]):
        assert a2 <= b1 + 1e-9


def test_short_song_single_real_window():
    assert plan_windows(12.5, 30, 15) == [(0.0, 12.5)]


def test_silence_marking_and_coverage():
    sr = 1000
    x = np.concatenate([0.3 * np.ones(10 * sr), np.zeros(10 * sr)]).astype(np.float32)
    ws = mark_windows(x, sr, plan_windows(20.0, 10, 10), -60.0)
    assert [w.silent for w in ws] == [False, True]
    assert coverage(ws, {0}) == "full"
    assert coverage(ws, set()) == "missing"
    ws3 = [Window(i, i * 10.0, i * 10.0 + 10, -20.0, False) for i in range(3)]
    assert coverage(ws3, {0, 2}) == "partial"


def test_lyric_blocks_keep_original_text():
    text = "あ\nい\nう\nえ\nお\nか\n\n\nき\n"
    blocks = split_blocks(text, max_lines=4)
    assert [b.text for b in blocks] == ["あ\nい\nう\nえ", "お\nか", "き"]
    assert blocks[2].line_start == 9 and blocks[0].evidence_id("t_x") == "lyr:t_x:0"


def test_manifest_ids_stable_and_update_preserves(tmp_path):
    songs = tmp_path / "data" / "songs"
    songs.mkdir(parents=True)
    (songs / "Artist - One.mp3").write_bytes(b"x")
    out = tmp_path / "data" / "manifest.json"
    doc, added, _ = init_manifest(out, songs, None, "jpn_Jpan", "Test")
    tid = doc["tracks"][0]["track_id"]
    assert tid == make_track_id("songs/Artist - One.mp3") and doc["tracks"][0]["title"] == "One"
    with pytest.raises(ManifestError):
        init_manifest(out, songs, None, "jpn_Jpan", "Test")
    doc["tracks"][0]["title"] = "Edited"
    out.write_text(json.dumps(doc), encoding="utf-8")
    (songs / "Artist - Two.wav").write_bytes(b"x")
    doc2, added2, _ = init_manifest(out, songs, None, "jpn_Jpan", "Test", update=True)
    assert len(added2) == 1 and doc2["tracks"][0]["title"] == "Edited" and doc2["tracks"][0]["track_id"] == tid
    # Lyrics named after the bare title attach to the existing not_provided track on --update.
    lyr = tmp_path / "data" / "lyrics"
    lyr.mkdir()
    (lyr / "One.txt").write_text("あ\n", encoding="utf-8")
    doc3, added3, attached = init_manifest(out, songs, lyr, "jpn_Jpan", "Test", update=True)
    assert added3 == [] and attached == [tid]
    assert doc3["tracks"][0]["lyrics"] == {"status": "available", "path": "lyrics/One.txt", "lang": "jpn_Jpan"}


def test_manifest_rejects_bad_lyrics_status(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"schema": "songweave.manifest.v1", "tracks": [{"track_id": "a", "audio": "a.mp3", "lyrics": {"status": "zero"}}]}))
    with pytest.raises(ManifestError):
        load_manifest(p)
    p.write_text(json.dumps({"schema": "songweave.manifest.v1", "tracks": [{"track_id": "a", "audio": "a.mp3", "lyrics": {"status": "available"}}]}))
    with pytest.raises(ManifestError):
        load_manifest(p)


def test_block_language_tags():
    assert block_lang("I want you\nso bad", "jpn_Jpan") == "eng_Latn"
    assert block_lang("ねえ I love you", "jpn_Jpan") == "jpn_Jpan"
    assert block_lang("ＮＩＰＰＯＮ", "jpn_Jpan") == "eng_Latn"
    assert block_lang("123 !!", "jpn_Jpan") == "jpn_Jpan"
