"""Interpretation cache (artifacts/interpretations/<kind>/*.json) and human review state."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..schemas import INTERPRETATIONS_SCHEMA, REVIEW_STATUSES

KINDS = ("pair_explanation", "lyric_understanding")


def record_path(cfg: Config, kind: str, interpretation_id: str) -> Path:
    safe = interpretation_id.replace(":", "_").replace("|", "_").replace("/", "_")
    return cfg.interpretations_dir / kind / f"{safe}.json"


def save(cfg: Config, rec: dict[str, Any]) -> Path:
    p = record_path(cfg, rec["kind"], rec["interpretation_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def load_all(cfg: Config) -> list[dict[str, Any]]:
    out = []
    for kind in KINDS:
        d = cfg.interpretations_dir / kind
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def find(cfg: Config, interpretation_id: str) -> dict[str, Any] | None:
    for kind in KINDS:
        p = record_path(cfg, kind, interpretation_id)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def set_review(cfg: Config, interpretation_id: str, status: str, reviewer: str, note: str | None) -> dict[str, Any]:
    if status not in REVIEW_STATUSES:
        raise ValueError(status)
    rec = find(cfg, interpretation_id)
    if rec is None:
        raise KeyError(f"no cached interpretation {interpretation_id}")
    if status == "approved" and rec["validation"]["status"] != "pass":
        raise ValueError("cannot approve an interpretation that failed citation/schema checks")
    rec["review"] = {
        "status": status,
        "reviewer": reviewer if status != "unreviewed" else None,
        "note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds") if status != "unreviewed" else None,
    }
    save(cfg, rec)
    return rec


def collect_for_export(cfg: Config) -> dict[str, Any]:
    """Only schema/citation-valid records are exported; the payload and raw text stay local."""
    items, failed = [], 0
    for rec in load_all(cfg):
        if rec["validation"]["status"] != "pass":
            failed += 1
            continue
        items.append(
            {
                "interpretation_id": rec["interpretation_id"],
                "kind": rec["kind"],
                "subject": rec["subject"],
                "model": rec["model"],
                "created_at": rec["created_at"],
                "prompt": rec["prompt"],
                "sent_scope": rec["sent_scope"],
                "output": rec["output"],
                "validation": rec["validation"],
                "review": rec["review"],
                "generation": "cached_real_api_response",
            }
        )
    from .translations import collect_translations

    translated, invalid = collect_translations(cfg, items)
    return {"schema": INTERPRETATIONS_SCHEMA, "items": items + translated, "failed_validation_count": failed + invalid}
