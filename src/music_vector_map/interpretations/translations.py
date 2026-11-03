"""Read locally authored translations. Never calls a model or changes source API records."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from ..config import Config
from .checks import check_output, payload_time_index
from .schemas import cited_ids


def output_hash(output: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(output, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def same_structure(source: Any, translated: Any, key: str = "") -> bool:
    """Only prose may change; dimensions, evidence IDs and array order must stay intact."""
    if isinstance(source, dict):
        return isinstance(translated, dict) and source.keys() == translated.keys() and all(
            same_structure(value, translated[k], k) for k, value in source.items()
        )
    if isinstance(source, list):
        return isinstance(translated, list) and len(source) == len(translated) and all(
            same_structure(a, b, key) for a, b in zip(source, translated)
        )
    if key in {"summary", "overview", "statement", "suggestion", "uncertainties"}:
        return isinstance(translated, str) and bool(translated.strip())
    return source == translated


def collect_translations(cfg: Config, sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    from .cache import find

    by_id = {s["interpretation_id"]: s for s in sources}
    # A real result in the requested language takes precedence over a translation.
    existing = {(s["kind"], json.dumps(s["subject"], sort_keys=True), s["prompt"]["output_language"]) for s in sources}
    items, failed = [], 0
    for path in sorted((cfg.interpretations_dir / "translations").glob("*.json")):
        try:
            translation = json.loads(path.read_text(encoding="utf-8"))
            source = by_id[translation["source_interpretation_id"]]
            lang = translation["language"]
            if lang not in {"en", "ja", "zh-Hans"} or lang == source["prompt"]["output_language"]:
                raise ValueError("invalid translation language")
            if translation["source_output_sha256"] != output_hash(source["output"]):
                raise ValueError("source changed")
            output = translation["output"]
            if not same_structure(source["output"], output):
                raise ValueError("translation changed structure or references")
            allowed = {eid for _, eid in cited_ids(source["kind"], source["output"])}
            raw_source = find(cfg, source["interpretation_id"])
            times = payload_time_index(raw_source.get("payload", {})) if raw_source else {}
            validation = check_output(source["kind"], output, allowed, times)
            if validation["status"] != "pass":
                raise ValueError("invalid translated output")
            # A translated paraphrase must not silently erase a warning on the source.
            validation["lint_flags"] += [f for f in source["validation"].get("lint_flags", []) if f not in validation["lint_flags"]]
            subject_key = (source["kind"], json.dumps(source["subject"], sort_keys=True), lang)
            if subject_key in existing:
                continue
            item = deepcopy(source)
            item.update(
                interpretation_id=f"{source['interpretation_id']}:translation:{lang}",
                generation="local_translation",
                output=output,
                validation=validation,
                review={"status": "unreviewed", "reviewer": None, "note": None, "reviewed_at": None},
                translation={k: v for k, v in translation.items() if k != "output"},
            )
            # Preserve the source generation date/model/scope; the translation has its own date.
            item["prompt"] = dict(source["prompt"], output_language=lang)
            items.append(item)
            existing.add(subject_key)
        except (KeyError, ValueError, TypeError):
            failed += 1
    return items, failed
