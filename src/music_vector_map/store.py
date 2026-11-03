"""Analysis records on disk: one NPZ (vectors) + one JSON (provenance, windows, coverage) per track and space.

artifacts/analysis/<space>/<track_id>.npz   unit_ids (int), embeddings (n, d) float32
artifacts/analysis/<space>/<track_id>.json  see docs/DATA_CONTRACTS.md, "Analysis record"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class AnalysisRecord:
    meta: dict[str, Any]
    unit_ids: np.ndarray
    embeddings: np.ndarray


def record_paths(analysis_dir: Path, space: str, track_id: str) -> tuple[Path, Path]:
    d = analysis_dir / space
    return d / f"{track_id}.npz", d / f"{track_id}.json"


def write_record(analysis_dir: Path, space: str, track_id: str, meta: dict[str, Any], unit_ids, embeddings) -> None:
    npz, js = record_paths(analysis_dir, space, track_id)
    npz.parent.mkdir(parents=True, exist_ok=True)
    emb = np.asarray(embeddings, dtype=np.float32)
    ids = np.asarray(unit_ids, dtype=np.int64)
    if emb.ndim != 2 or emb.shape[0] != ids.shape[0]:
        raise ValueError(f"{space}/{track_id}: embeddings {emb.shape} do not match {ids.shape[0]} unit ids")
    if not np.all(np.isfinite(emb)):
        raise ValueError(f"{space}/{track_id}: non-finite embedding values")
    tmp = npz.with_name(npz.stem + ".tmp.npz")
    np.savez(tmp, unit_ids=ids, embeddings=emb)
    tmp.replace(npz)
    meta = dict(meta, space=space, track_id=track_id, n_units=int(ids.shape[0]), dim=int(emb.shape[1]) if emb.size else 0)
    js.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_meta(analysis_dir: Path, space: str, track_id: str) -> dict[str, Any] | None:
    _, js = record_paths(analysis_dir, space, track_id)
    if not js.is_file():
        return None
    return json.loads(js.read_text(encoding="utf-8"))


def read_record(analysis_dir: Path, space: str, track_id: str) -> AnalysisRecord | None:
    npz, _ = record_paths(analysis_dir, space, track_id)
    meta = read_meta(analysis_dir, space, track_id)
    if meta is None or not npz.is_file():
        return None
    with np.load(npz) as z:
        return AnalysisRecord(meta=meta, unit_ids=z["unit_ids"], embeddings=z["embeddings"])


def is_current(meta: dict[str, Any] | None, input_sha256: str, settings_hash: str) -> bool:
    return bool(
        meta
        and meta.get("input_sha256") == input_sha256
        and meta.get("settings_hash") == settings_hash
        and meta.get("coverage") == "full"
    )
