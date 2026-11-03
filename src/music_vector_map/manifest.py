"""Track manifest: stable track IDs, media paths relative to the manifest, lyric status."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schemas import AUDIO_EXTENSIONS, LYRICS_STATUSES, MANIFEST_SCHEMA


class ManifestError(ValueError):
    pass


@dataclass
class LyricsRef:
    status: str = "not_provided"
    path: str | None = None
    lang: str | None = None
    note: str | None = None


@dataclass
class Track:
    track_id: str
    title: str
    artist: str | None
    audio: str
    lyrics: LyricsRef = field(default_factory=LyricsRef)
    base_dir: Path = Path(".")

    @property
    def audio_path(self) -> Path:
        return (self.base_dir / self.audio).resolve()

    @property
    def lyrics_path(self) -> Path | None:
        return (self.base_dir / self.lyrics.path).resolve() if self.lyrics.path else None


@dataclass
class Manifest:
    path: Path
    dataset_id: str
    dataset_name: str
    kind: str  # "real" or "fixture"
    tracks: list[Track]

    def by_id(self) -> dict[str, Track]:
        return {t.track_id: t for t in self.tracks}


def make_track_id(rel_audio: str) -> str:
    norm = unicodedata.normalize("NFC", rel_audio.replace("\\", "/"))
    return "t_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def _parse_name(stem: str) -> tuple[str | None, str]:
    stem = unicodedata.normalize("NFC", stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip() or None, title.strip()
    return None, stem


def load_manifest(path: Path) -> Manifest:
    path = path.resolve()
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path} (create one with `mvm init-manifest`)")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise ManifestError(f"unsupported manifest schema {raw.get('schema')!r}; expected {MANIFEST_SCHEMA}")
    base = path.parent
    tracks: list[Track] = []
    seen: set[str] = set()
    for i, t in enumerate(raw.get("tracks", [])):
        tid = t.get("track_id")
        if not tid or not isinstance(tid, str):
            raise ManifestError(f"track #{i} has no track_id")
        if tid in seen:
            raise ManifestError(f"duplicate track_id {tid}")
        seen.add(tid)
        audio = t.get("audio")
        if not audio:
            raise ManifestError(f"{tid}: missing audio path")
        if Path(audio).suffix.lower() not in AUDIO_EXTENSIONS:
            raise ManifestError(f"{tid}: unsupported audio type {Path(audio).suffix}")
        ly = t.get("lyrics") or {}
        status = ly.get("status", "not_provided")
        if status not in LYRICS_STATUSES:
            raise ManifestError(f"{tid}: invalid lyrics status {status!r}")
        if status in ("available", "unverified_transcript") and not ly.get("path"):
            raise ManifestError(f"{tid}: lyrics status {status} requires a path")
        tracks.append(
            Track(
                track_id=tid,
                title=t.get("title") or Path(audio).stem,
                artist=t.get("artist"),
                audio=audio,
                lyrics=LyricsRef(status=status, path=ly.get("path"), lang=ly.get("lang"), note=ly.get("note")),
                base_dir=base,
            )
        )
    ds = raw.get("dataset", {})
    kind = ds.get("kind", "real")
    if kind not in ("real", "fixture"):
        raise ManifestError(f"dataset.kind must be 'real' or 'fixture', got {kind!r}")
    return Manifest(path=path, dataset_id=ds.get("id", "local"), dataset_name=ds.get("name", "Local library"), kind=kind, tracks=tracks)


def check_files(manifest: Manifest) -> list[str]:
    """Return human-readable problems with referenced files (missing audio or lyric files)."""
    problems = []
    for t in manifest.tracks:
        if not t.audio_path.is_file():
            problems.append(f"{t.track_id}: audio file missing: {t.audio}")
        if t.lyrics.path and not t.lyrics_path.is_file():  # type: ignore[union-attr]
            problems.append(f"{t.track_id}: lyrics file missing: {t.lyrics.path}")
    return problems


def find_lyrics_file(lyrics_dir: Path, stem: str, title: str) -> Path | None:
    """Lyrics may be named after the audio file stem or after the bare title."""
    names = {unicodedata.normalize("NFC", n) for n in (stem, title)}
    for p in sorted(lyrics_dir.glob("*.txt")):
        if unicodedata.normalize("NFC", p.stem) in names:
            return p
    return None


def scan_tracks(manifest_dir: Path, audio_dir: Path, lyrics_dir: Path | None, default_lang: str) -> list[dict[str, Any]]:
    entries = []
    for p in sorted(audio_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        rel = p.resolve().relative_to(manifest_dir.resolve()).as_posix()
        artist, title = _parse_name(p.stem)
        lyrics: dict[str, Any] = {"status": "not_provided", "path": None, "lang": None}
        if lyrics_dir is not None:
            cand = find_lyrics_file(lyrics_dir, p.stem, title)
            if cand is not None:
                lyrics = {
                    "status": "available",
                    "path": cand.resolve().relative_to(manifest_dir.resolve()).as_posix(),
                    "lang": default_lang,
                }
        entries.append({"track_id": make_track_id(rel), "title": title, "artist": artist, "audio": rel, "lyrics": lyrics})
    return entries


def init_manifest(
    out: Path,
    audio_dir: Path,
    lyrics_dir: Path | None,
    default_lang: str,
    dataset_name: str,
    update: bool = False,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Create or extend a manifest. Existing IDs and titles are preserved; lyrics attach only to not_provided tracks."""
    out = out.resolve()
    base = out.parent
    scanned = scan_tracks(base, audio_dir, lyrics_dir, default_lang)
    added: list[str] = []
    attached: list[str] = []
    if out.exists():
        if not update:
            raise ManifestError(f"{out} exists; pass --update to add new files without changing existing entries")
        doc = json.loads(out.read_text(encoding="utf-8"))
        by_audio = {t["audio"]: t for t in doc["tracks"]}
        for e in scanned:
            known = by_audio.get(e["audio"])
            if known is None:
                doc["tracks"].append(e)
                added.append(e["track_id"])
            elif (known.get("lyrics") or {}).get("status", "not_provided") == "not_provided" and e["lyrics"]["status"] == "available":
                # Newly supplied lyrics attach to an existing track; any other status was set deliberately.
                known["lyrics"] = e["lyrics"]
                attached.append(known["track_id"])
    else:
        doc = {
            "schema": MANIFEST_SCHEMA,
            "dataset": {"id": "local-library", "name": dataset_name, "kind": "real"},
            "tracks": scanned,
        }
        added = [e["track_id"] for e in scanned]
    ids = [t["track_id"] for t in doc["tracks"]]
    if len(ids) != len(set(ids)):
        raise ManifestError("track_id collision while scanning; edit the manifest to disambiguate")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc, added, attached
