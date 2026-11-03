"""`mvm validate-export`: mechanical checks on a written bundle (no model or network access)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..interpretations.schemas import cited_ids
from ..schemas import EXPORT_SCHEMA, INTERPRETATIONS_SCHEMA, PRIMARY_VIEWS, REVIEW_STATUSES


def collect_evidence_ids(data: dict[str, Any]) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    dupes: list[str] = []

    def add(i: str) -> None:
        if i in ids:
            dupes.append(i)
        ids.add(i)

    for t in data["tracks"]:
        for b in t["lyrics"].get("blocks", []) or []:
            add(b["evidence_id"])
    for p in data["pairs"].values():
        for rel in p["views"].values():
            if not rel.get("available"):
                continue
            add(rel["relation_id"])
            for e in rel.get("excerpts", []) + rel.get("contrasts", []) + rel.get("lyric_pairs", []):
                add(e["id"])
    return ids, dupes


def validate_export_data(data: dict[str, Any], media_root: Path | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    if data.get("schema") != EXPORT_SCHEMA:
        return [f"schema {data.get('schema')!r} != {EXPORT_SCHEMA}"], warns
    if data["dataset"].get("kind") == "fixture":
        warns.append("dataset is a FIXTURE: software-test data, not evidence of musical quality")
    tracks = {t["track_id"]: t for t in data["tracks"]}
    if len(tracks) != len(data["tracks"]):
        errors.append("duplicate track ids")
    views = [v["view_id"] for v in data["views"]]
    if sorted(views) != sorted(PRIMARY_VIEWS):
        errors.append(f"views {views} != primary views {list(PRIMARY_VIEWS)}")
    for v in data["views"]:
        inc = set(v["included"])
        if not inc <= set(tracks):
            errors.append(f"{v['view_id']}: included unknown tracks")
        exc = {e["track_id"] for e in v["excluded"]}
        if inc & exc:
            errors.append(f"{v['view_id']}: tracks both included and excluded")
        if inc | exc != set(tracks):
            errors.append(f"{v['view_id']}: some tracks neither included nor excluded")
        for tid, xy in (v.get("coords") or {}).items():
            if tid not in inc or len(xy) != 2 or not all(math.isfinite(c) and -1.000001 <= c <= 1.000001 for c in xy):
                errors.append(f"{v['view_id']}: bad coords for {tid}")
        for tid, full in (v.get("ranking") or {}).items():
            if len(full) != len(inc) - 1 or full[: len((v.get("neighbors") or {}).get(tid, []))] != (v.get("neighbors") or {}).get(tid, []):
                errors.append(f"{v['view_id']}: ranking of {tid} incomplete or inconsistent with neighbours")
        for tid, nbrs in list((v.get("neighbors") or {}).items()) + list((v.get("ranking") or {}).items()):
            scores = [n["score"] for n in nbrs]
            if any(n["track_id"] == tid for n in nbrs):
                errors.append(f"{v['view_id']}: {tid} lists itself as a neighbour")
            if any(n["track_id"] not in inc for n in nbrs):
                errors.append(f"{v['view_id']}: {tid} has a neighbour outside the view")
            if scores != sorted(scores, reverse=True):
                errors.append(f"{v['view_id']}: neighbours of {tid} not ordered by original-space score")
        if v["view_id"] == "lyrics_sonar":
            for e in v["excluded"]:
                st = tracks[e["track_id"]]["lyrics"]["status"]
                if st != "available" and not e["reason"].startswith("lyrics_"):
                    errors.append(f"lyrics_sonar: {e['track_id']} status {st} excluded for wrong reason")
    ids = sorted(tracks)
    expected = {f"{a}|{b}" for i, a in enumerate(ids) for b in ids[i + 1 :]}
    if set(data["pairs"]) != expected:
        errors.append(f"pair set mismatch: {len(data['pairs'])} present, {len(expected)} expected")
    for key, p in data["pairs"].items():
        a, b = p["a"], p["b"]
        if key != f"{a}|{b}" or a >= b:
            errors.append(f"pair {key}: non-canonical")
            continue
        for vid, rel in p["views"].items():
            view = next(v for v in data["views"] if v["view_id"] == vid)
            in_view = a in view["included"] and b in view["included"]
            if rel["available"] != in_view:
                errors.append(f"{key} {vid}: availability does not match view membership")
            if not rel["available"]:
                if "score" in rel:
                    errors.append(f"{key} {vid}: unavailable relation carries a score (missing must not be zero)")
                continue
            if not (-1.000001 <= rel["score"] <= 1.000001):
                errors.append(f"{key} {vid}: score out of cosine range")
            for e in rel.get("excerpts", []):
                for side, tid in (("a", a), ("b", b)):
                    seg = e[side]
                    if seg["track_id"] != tid or not (0 <= seg["start"] < seg["end"] <= tracks[tid]["duration_seconds"] + 0.05):
                        errors.append(f"{e['id']}: bad {side} segment {seg}")
            for c in rel.get("contrasts", []):
                seg = c["segment"]
                if seg["track_id"] not in (a, b) or not (0 <= seg["start"] < seg["end"] <= tracks[seg["track_id"]]["duration_seconds"] + 0.05):
                    errors.append(f"{c['id']}: bad segment {seg}")
    evidence, dupes = collect_evidence_ids(data)
    if dupes:
        errors.append(f"duplicate evidence ids: {dupes[:5]}")
    if media_root is not None:
        for t in data["tracks"]:
            if not (media_root / t["media"]).is_file():
                errors.append(f"{t['track_id']}: media {t['media']} missing")
    return errors, warns


def validate_interpretations(interp: dict[str, Any], data: dict[str, Any]) -> list[str]:
    errors = []
    if interp.get("schema") != INTERPRETATIONS_SCHEMA:
        return [f"interpretations schema {interp.get('schema')!r}"]
    evidence, _ = collect_evidence_ids(data)
    tracks = {t["track_id"] for t in data["tracks"]}
    for it in interp["items"]:
        iid = it["interpretation_id"]
        subj = it["subject"].get("pair") or [it["subject"].get("track_id")]
        if not set(subj) <= tracks:
            errors.append(f"{iid}: subject not in dataset")
        if it["validation"]["status"] != "pass":
            errors.append(f"{iid}: exported despite failed validation")
        if it["review"]["status"] not in REVIEW_STATUSES:
            errors.append(f"{iid}: bad review status")
        if it.get("generation") == "local_translation":
            from ..interpretations.translations import output_hash, same_structure

            provenance = it.get("translation", {})
            source = next((s for s in interp["items"] if s["interpretation_id"] == provenance.get("source_interpretation_id")), None)
            if (not source or source.get("generation") != "cached_real_api_response"
                    or source["subject"] != it["subject"] or source["kind"] != it["kind"]
                    or provenance.get("language") != it["prompt"]["output_language"]
                    or provenance.get("source_output_sha256") != output_hash(source["output"])
                    or not same_structure(source["output"], it["output"])):
                errors.append(f"{iid}: invalid translation provenance or references")
        elif it.get("generation") != "cached_real_api_response":
            errors.append(f"{iid}: unknown interpretation provenance")
        for where, eid in cited_ids(it["kind"], it["output"]):
            if eid not in evidence:
                errors.append(f"{iid} {where}: evidence {eid} not present in current export (stale; regenerate)")
    return errors


def validate_export_dir(d: Path) -> tuple[list[str], list[str]]:
    p = d / "export.json"
    if not p.is_file():
        return [f"{p} missing"], []
    data = json.loads(p.read_text(encoding="utf-8"))
    errors, warns = validate_export_data(data, d)
    ip = d / "interpretations.json"
    if ip.is_file():
        errors += validate_interpretations(json.loads(ip.read_text(encoding="utf-8")), data)
    else:
        warns.append("interpretations.json missing")
    return errors, warns
