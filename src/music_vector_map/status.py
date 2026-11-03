"""`mvm status`: what has actually been analysed, exported and generated (no network)."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .config import Config
from .interpretations.cache import load_all
from .manifest import load_manifest
from .schemas import PRIMARY_VIEWS, VIEW_SPACE
from .store import read_meta


def status_report(cfg: Config) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        m = load_manifest(cfg.manifest_path)
    except Exception as e:  # noqa: BLE001 - reported, not raised
        return {"manifest": f"unavailable: {e}"}
    out["dataset"] = {"name": m.dataset_name, "kind": m.kind, "tracks": len(m.tracks)}
    out["lyrics_status"] = dict(Counter(t.lyrics.status for t in m.tracks))
    cov = {}
    for v in PRIMARY_VIEWS:
        c = Counter()
        for t in m.tracks:
            meta = read_meta(cfg.analysis_dir, VIEW_SPACE[v], t.track_id)
            c[meta.get("coverage") if meta else "not_analyzed"] += 1
        cov[v] = dict(c)
    out["analysis_coverage"] = cov
    exp = cfg.export_dir / "export.json"
    if exp.is_file():
        d = json.loads(exp.read_text(encoding="utf-8"))
        out["export"] = {"generated_at": d["generated_at"], "views": {v["view_id"]: v["status"] for v in d["views"]}}
    else:
        out["export"] = None
    recs = load_all(cfg)
    out["interpretations"] = {
        "total": len(recs),
        "by_kind": dict(Counter(r["kind"] for r in recs)),
        "validation": dict(Counter(r["validation"]["status"] for r in recs)),
        "review": dict(Counter(r["review"]["status"] for r in recs)),
    }
    return out
