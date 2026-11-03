"""`mvm export`: relations, evidence and map coordinates -> artifacts/export (local only, no API calls).

Writes:
  export.json           tracks, views, neighbours, all pair relations with evidence IDs
  interpretations.json  validated cached Meta interpretations (see interpretations/)
  media/<track_id>.ext  symlinks to the original audio (read-only playback; same time base)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..audio.decode import probe
from ..config import Config
from ..manifest import Manifest, load_manifest
from ..relations.compute import ViewSpace, l2n, least_matched, top_unit_pairs, track_vector, unit_similarity
from ..schemas import AUDIO_VIEWS, EXPORT_SCHEMA, LYRICS_EMBEDDABLE, PRIMARY_VIEWS, VIEW_LABELS_ZH, VIEW_SPACE
from ..store import read_record

MODEL_LABELS = {
    "overall_peav": "Meta PE-AV (pe-av-small, audio-only)",
    "melody_merit": "MERIT melody head · MERT-v1-330M",
    "rhythm_merit": "MERIT rhythm head · MERT-v1-330M",
    "timbre_merit": "MERIT timbre head · MERT-v1-330M",
    "lyrics_sonar": "Meta SONAR text encoder",
}


def pair_key(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"{x}|{y}"


def _r(x: float) -> float:
    return round(float(x), 6)


def _load_view(cfg: Config, manifest: Manifest, view_id: str) -> tuple[ViewSpace | None, list[dict], dict[str, dict], dict]:
    """Return (space or None, excluded, per-track unit info, provenance)."""
    space = VIEW_SPACE[view_id]
    excluded: list[dict] = []
    vecs, ids = [], []
    units: dict[str, np.ndarray] = {}
    unit_ids: dict[str, list[int]] = {}
    info: dict[str, dict] = {}
    prov: dict[str, Any] = {}
    for t in manifest.tracks:
        if view_id == "lyrics_sonar" and t.lyrics.status not in LYRICS_EMBEDDABLE:
            excluded.append({"track_id": t.track_id, "reason": f"lyrics_{t.lyrics.status}"})
            continue
        rec = read_record(cfg.analysis_dir, space, t.track_id)
        if rec is None:
            excluded.append({"track_id": t.track_id, "reason": "not_analyzed"})
            continue
        if rec.meta.get("coverage") != "full":
            excluded.append({"track_id": t.track_id, "reason": f"coverage_{rec.meta.get('coverage')}"})
            continue
        if view_id == "lyrics_sonar" and rec.meta.get("input_sha256") is None:
            excluded.append({"track_id": t.track_id, "reason": "lyrics_record_invalid"})
            continue
        ids.append(t.track_id)
        vecs.append(track_vector(rec.embeddings))
        units[t.track_id] = l2n(rec.embeddings.astype(np.float64))
        unit_ids[t.track_id] = [int(u) for u in rec.unit_ids]
        info[t.track_id] = rec.meta
        if not prov:
            prov = {
                "model_info": rec.meta.get("model_info"),
                "settings": rec.meta.get("settings"),
                "settings_hash": rec.meta.get("settings_hash"),
            }
        elif rec.meta.get("settings_hash") != prov["settings_hash"]:
            raise RuntimeError(f"{view_id}: mixed preprocessing settings across tracks; re-run `mvm analyze --force` for consistency")
    if not ids:
        return None, excluded, info, prov
    vs = ViewSpace(view_id=view_id, space=space, track_ids=ids, vectors=np.stack(vecs), units=units, unit_ids=unit_ids)
    return vs, excluded, info, prov


def _spans(meta: dict, unit_ids: list[int]) -> list[tuple[float, float]]:
    by_idx = {w["index"]: (float(w["start"]), float(w["end"])) for w in meta["windows"]}
    return [by_idx[u] for u in unit_ids]


def _audio_pair_evidence(view_id: str, vs: ViewSpace, info: dict[str, dict], a: str, b: str, n: int) -> tuple[list[dict], list[dict]]:
    S = unit_similarity(vs.units[a], vs.units[b])
    sa, sb = _spans(info[a], vs.unit_ids[a]), _spans(info[b], vs.unit_ids[b])
    excerpts = []
    for k, (i, j, s) in enumerate(top_unit_pairs(S, sa, sb, n)):
        excerpts.append(
            {
                "id": f"exc:{view_id}:{a}:{b}:{k}",
                "kind": "similar_excerpt",
                "score": _r(s),
                "a": {"track_id": a, "start": sa[i][0], "end": sa[i][1]},
                "b": {"track_id": b, "start": sb[j][0], "end": sb[j][1]},
            }
        )
    contrasts = []
    for side, tid, spans in ((0, a, sa), (1, b, sb)):
        idx, best = least_matched(S, side)
        contrasts.append(
            {
                "id": f"con:{view_id}:{a}:{b}:{tid}",
                "kind": "contrast_excerpt",
                "best_match_score": _r(best),
                "segment": {"track_id": tid, "start": spans[idx][0], "end": spans[idx][1]},
            }
        )
    return excerpts, contrasts


def _lyrics_pair_evidence(vs: ViewSpace, a: str, b: str, n: int) -> list[dict]:
    S = unit_similarity(vs.units[a], vs.units[b])
    out = []
    for k, (i, j, s) in enumerate(top_unit_pairs(S, None, None, n)):
        out.append(
            {
                "id": f"lpair:{a}:{b}:{k}",
                "kind": "similar_lyrics",
                "score": _r(s),
                "a": {"track_id": a, "block": vs.unit_ids[a][i], "evidence_id": f"lyr:{a}:{vs.unit_ids[a][i]}"},
                "b": {"track_id": b, "block": vs.unit_ids[b][j], "evidence_id": f"lyr:{b}:{vs.unit_ids[b][j]}"},
            }
        )
    return out


def build_export_data(cfg: Config, manifest: Manifest, log: Callable[[str], None] = print) -> dict[str, Any]:
    ex = cfg.section("export")
    k, n_exc = int(ex["neighbors_k"]), int(ex["excerpts_per_pair"])
    views_out, spaces, infos = [], {}, {}
    for view_id in PRIMARY_VIEWS:
        vs, excluded, info, prov = _load_view(cfg, manifest, view_id)
        spaces[view_id], infos[view_id] = vs, info
        entry: dict[str, Any] = {
            "view_id": view_id,
            "label_zh": VIEW_LABELS_ZH[view_id],
            "space": VIEW_SPACE[view_id],
            "model_label": MODEL_LABELS[view_id],
            "provenance": prov,
            "included": vs.track_ids if vs else [],
            "excluded": excluded,
            "status": "ready" if vs and len(vs.track_ids) >= 2 else ("insufficient" if vs else "unavailable"),
        }
        if vs:
            coords, ev = vs.pca2()
            entry["coords"] = coords
            entry["explained_variance_2d"] = [round(v, 4) for v in ev]
            entry["neighbors"] = {t: vs.neighbors(t, k) for t in vs.track_ids}
            # Full original-space ranking per song (drives the Focus view's radii).
            entry["ranking"] = {t: vs.neighbors(t, len(vs.track_ids) - 1) for t in vs.track_ids}
            tri = vs.sim[np.triu_indices(len(vs.track_ids), 1)]
            if tri.size:
                entry["pair_score_stats"] = {"min": _r(tri.min()), "median": _r(np.median(tri)), "max": _r(tri.max()), "n_pairs": int(tri.size)}
        views_out.append(entry)
        log(f"view {view_id}: {entry['status']} ({len(entry['included'])} included, {len(excluded)} excluded)")

    tracks_out = []
    for t in manifest.tracks:
        p = probe(t.audio_path)
        cov = {}
        for v in PRIMARY_VIEWS:
            vs = spaces[v]
            if vs and t.track_id in vs.index:
                cov[v] = "full"
            else:
                reason = next((e["reason"] for e in next(x for x in views_out if x["view_id"] == v)["excluded"] if e["track_id"] == t.track_id), "unknown")
                cov[v] = reason
        lyr: dict[str, Any] = {"status": t.lyrics.status, "lang": t.lyrics.lang}
        sonar_meta = infos["lyrics_sonar"].get(t.track_id)
        if sonar_meta:
            lyr["blocks"] = [dict(b, evidence_id=f"lyr:{t.track_id}:{b['index']}") for b in sonar_meta["blocks"]]
        tracks_out.append(
            {
                "track_id": t.track_id,
                "title": t.title,
                "artist": t.artist,
                "duration_seconds": round(p["duration_seconds"], 3),
                "media": f"media/{t.track_id}{t.audio_path.suffix.lower()}",
                "lyrics": lyr,
                "coverage": cov,
            }
        )

    pairs: dict[str, Any] = {}
    pair_ranks = {v: (spaces[v].pair_ranks() if spaces[v] and len(spaces[v].track_ids) >= 2 else {}) for v in PRIMARY_VIEWS}
    ids = [t.track_id for t in manifest.tracks]
    for a, b in combinations(sorted(ids), 2):
        pv: dict[str, Any] = {}
        for v in PRIMARY_VIEWS:
            vs = spaces[v]
            if not vs or a not in vs.index or b not in vs.index:
                missing = [x for x in (a, b) if not vs or x not in vs.index]
                pv[v] = {"available": False, "missing": missing}
                continue
            rel = {
                "available": True,
                "relation_id": f"rel:{v}:{a}:{b}",
                "score": _r(vs.score(a, b)),
                "rank_b_for_a": vs.rank_of(a, b),
                "rank_a_for_b": vs.rank_of(b, a),
                "n_candidates": len(vs.track_ids) - 1,
                "pair_rank": pair_ranks[v].get((a, b)),
                "n_pairs": len(pair_ranks[v]),
            }
            if v in AUDIO_VIEWS:
                rel["excerpts"], rel["contrasts"] = _audio_pair_evidence(v, vs, infos[v], a, b, n_exc)
            else:
                rel["lyric_pairs"] = _lyrics_pair_evidence(vs, a, b, n_exc)
            pv[v] = rel
        pairs[pair_key(a, b)] = {"a": a, "b": b, "views": pv}

    return {
        "schema": EXPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"id": manifest.dataset_id, "name": manifest.dataset_name, "kind": manifest.kind, "track_count": len(manifest.tracks)},
        "notices": [
            "Scores are cosine similarities inside each model's own space: not percentages, not comparable across dimensions.",
            "Map coordinates are a 2-D PCA approximation with no musical meaning on the axes; neighbours come from the original space.",
        ],
        "views": views_out,
        "tracks": tracks_out,
        "pairs": pairs,
    }


def _link_media(cfg: Config, manifest: Manifest, out_dir: Path) -> None:
    media = out_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for t in manifest.tracks:
        name = f"{t.track_id}{t.audio_path.suffix.lower()}"
        wanted.add(name)
        link = media / name
        if link.is_symlink() or link.exists():
            if link.is_symlink() and Path(os.readlink(link)) == t.audio_path:
                continue
            link.unlink()
        link.symlink_to(t.audio_path)
    for p in media.iterdir():
        if p.name not in wanted and p.is_symlink():
            p.unlink()


def write_interpretations(cfg: Config) -> Path:
    from ..interpretations.cache import collect_for_export

    out = cfg.export_dir / "interpretations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: generation jobs may run in parallel with the server reading this file.
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(collect_for_export(cfg), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out


def build_export(cfg: Config, manifest_path: Path | None = None, log: Callable[[str], None] = print) -> Path:
    manifest = load_manifest(manifest_path or cfg.manifest_path)
    data = build_export_data(cfg, manifest, log)
    out_dir = cfg.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "export.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    _link_media(cfg, manifest, out_dir)
    write_interpretations(cfg)
    return path
