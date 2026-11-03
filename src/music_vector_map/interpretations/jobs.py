"""`mvm generate understand-lyrics|explain`: explicit, scoped, cached Meta Model API jobs."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from .cache import find, save
from .checks import check_output, payload_time_index, quote_flags
from .client import MetaApiError, MetaClient, read_api_key, refuse_training_models
from .payload import build_lyrics_payload, build_pair_payload
from .prompts import load_prompt
from .schemas import LYRICS_SCHEMA, PAIR_SCHEMA


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _load_export(cfg: Config) -> dict[str, Any]:
    p = cfg.export_dir / "export.json"
    if not p.is_file():
        raise FileNotFoundError("no export found; run `mvm export` first")
    return json.loads(p.read_text(encoding="utf-8"))


def _scope(payload: dict[str, Any], allow_lyrics: bool) -> dict[str, Any]:
    if payload["task"] == "pair_explanation":
        ids = [payload["tracks"]["A"], payload["tracks"]["B"]]
        lyrics = bool(payload["lyrics"].get("sent"))
        dims = [d["view_id"] for d in payload["dimensions"]]
    else:
        ids, lyrics, dims = [payload["track"]], True, ["lyrics_sonar"]
    return {
        "track_ids": ids,
        "audio": False,
        "embedding_vectors": False,
        "titles_or_artist": False,
        "lyrics_text": lyrics,
        "lyrics_upload_flag": allow_lyrics,
        "dimensions": dims,
        "bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
    }


def all_pair_items(export: dict[str, Any]) -> list[tuple[str, Any]]:
    return [("pair_explanation", (p["a"], p["b"])) for p in export["pairs"].values()]


def _items(args, export: dict[str, Any] | None = None) -> list[tuple[str, Any]]:
    if args.task == "explain" and getattr(args, "all_pairs", False):
        return all_pair_items(export or {"pairs": {}})
    if args.task == "explain":
        out = []
        for tok in args.pairs.split(","):
            tok = tok.strip()
            if not tok:
                continue
            a, sep, b = tok.partition(":")
            if not sep or not a or not b or a == b:
                raise ValueError(f"bad pair {tok!r}; use A:B with two different track IDs")
            out.append(("pair_explanation", (a, b)))
        return out
    return [("lyric_understanding", t.strip()) for t in args.tracks.split(",") if t.strip()]


def prepare_job(cfg: Config, export: dict[str, Any], kind: str, subject: Any, allow: bool, lang: str, model: str) -> dict[str, Any]:
    """Build the exact outbound payload, allowed evidence IDs and cache key for one item."""
    if kind == "pair_explanation":
        payload, allowed = build_pair_payload(export, subject[0], subject[1], allow)
        subj: dict[str, Any] = {"pair": [payload["tracks"]["A"], payload["tracks"]["B"]]}
    else:
        payload, allowed = build_lyrics_payload(export, subject)
        subj = {"track_id": subject}
    prompt = load_prompt(cfg, kind, lang)
    key = _sha({"payload": payload, "model": model, "prompt": prompt.sha256})[:12]
    sid = subj.get("track_id") or "|".join(subj["pair"])
    return {"kind": kind, "subject": subj, "id": f"{kind}:{sid}:{key}", "payload": payload, "allowed": allowed, "prompt": prompt, "scope": _scope(payload, allow), "lang": lang}


def make_client(cfg: Config, model: str) -> MetaClient:
    meta = cfg.section("meta_api")
    if not meta.get("enabled"):
        raise MetaApiError("Meta API generation is disabled in config/songweave.toml")
    key_value = read_api_key(cfg.root, list(meta["key_env"]))
    if not key_value:
        raise MetaApiError("no API key in META_API_KEY / MODEL_API_KEY (environment or .env)")
    return MetaClient(meta["base_url"], key_value, model, float(meta["timeout_seconds"]), int(meta["max_completion_tokens"]))


def execute_job(cfg: Config, client: MetaClient, j: dict[str, Any], model: str, force: bool = False) -> tuple[str, dict[str, Any] | str]:
    """Run one prepared job (or reuse a valid cached result). Returns (status, record or error).

    status: "cached" | "ok" | "invalid" | "failed". Safe to call from several threads: each record
    is saved to its own file.
    """
    meta = cfg.section("meta_api")
    cached = find(cfg, j["id"])
    if cached and not force and cached["validation"]["status"] == "pass":
        return "cached", cached
    schema = PAIR_SCHEMA if j["kind"] == "pair_explanation" else LYRICS_SCHEMA
    user = json.dumps(j["payload"], ensure_ascii=False)
    attempts: list[dict[str, Any]] = []
    output, check, comp = None, None, None
    for attempt in range(2):
        msg = user
        if attempt and check:
            msg = user + "\n\nYour previous answer failed validation: " + "; ".join(check["errors"][:8]) + ". Cite only evidence_id values present in the payload."
        try:
            comp = client.chat_json(j["prompt"].text, msg, j["kind"], schema)
        except MetaApiError as e:
            attempts.append({"error": str(e)})
            break
        try:
            output = json.loads(comp.content or "")
        except json.JSONDecodeError:
            output = None
        check = check_output(j["kind"], output, j["allowed"], payload_time_index(j["payload"])) if output is not None else {"status": "fail", "errors": [f"unparseable content (finish_reason={comp.finish_reason})"], "lint_flags": []}
        if output is not None and check["status"] == "pass":
            lyr = j["payload"].get("blocks") or j["payload"].get("lyrics", {}).get("blocks") or []
            if lyr:
                check["lint_flags"] += quote_flags(output, {b["evidence_id"]: b["original_text"] for b in lyr})
        attempts.append({"response_id": comp.response_id, "finish_reason": comp.finish_reason, "latency_seconds": comp.latency_seconds, "usage": comp.usage, "validation": check["status"]})
        if check["status"] == "pass":
            break
    if comp is None or check is None:
        return "failed", attempts[-1].get("error", "no response") if attempts else "no response"
    rec = {
        "interpretation_id": j["id"],
        "kind": j["kind"],
        "subject": j["subject"],
        "model": comp.model or model,
        "endpoint": meta["base_url"] + "/chat/completions",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt": {"name": j["prompt"].name, "version": j["prompt"].version, "sha256": j["prompt"].sha256, "output_language": j["lang"]},
        "sent_scope": j["scope"],
        "payload_sha256": _sha(j["payload"]),
        "payload": j["payload"],
        "allowed_evidence_ids": sorted(j["allowed"]),
        "raw_content": comp.content,
        "output": output,
        "validation": dict(check, checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "attempts": attempts,
        "review": {"status": "unreviewed", "reviewer": None, "note": None, "reviewed_at": None},
    }
    save(cfg, rec)
    return ("ok" if check["status"] == "pass" else "invalid"), rec


def run_generate(cfg: Config, args) -> int:
    meta = cfg.section("meta_api")
    model = args.model or meta["model"]
    try:
        refuse_training_models(model)
    except MetaApiError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    allow = bool(args.allow_lyrics_upload)
    if args.task == "understand-lyrics" and not allow and not args.dry_run:
        print("BLOCKED: understand-lyrics sends original lyrics; re-run with --allow-lyrics-upload for this invocation (see --dry-run first)", file=sys.stderr)
        return 2
    export = _load_export(cfg)
    items = _items(args, export)
    cap = args.max_items or int(meta["max_items_per_job"])
    if len(items) > cap:
        print(f"BLOCKED: {len(items)} items exceed the per-job cap of {cap}; pass --max-items {len(items)} to raise it explicitly", file=sys.stderr)
        return 2
    lang = getattr(args, "lang", None) or meta.get("output_language", "en")

    jobs = []
    for kind, subject in items:
        try:
            jobs.append(prepare_job(cfg, export, kind, subject, allow, lang, model))
        except (KeyError, ValueError) as e:
            print(f"SKIP {subject}: {e}", file=sys.stderr)
    if not jobs:
        print("nothing to do", file=sys.stderr)
        return 1

    if args.dry_run:
        out_dir = cfg.interpretations_dir / "dryrun"
        out_dir.mkdir(parents=True, exist_ok=True)
        for j in jobs:
            p = out_dir / (j["id"].replace(":", "_").replace("|", "_") + ".json")
            p.write_text(json.dumps({"scope": j["scope"], "system_prompt_sha256": j["prompt"].sha256, "payload": j["payload"]}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"DRY RUN {j['id']}\n  would send to {meta['base_url']} model={model}\n  scope: {json.dumps(j['scope'], ensure_ascii=False)}\n  evidence ids: {len(j['allowed'])}\n  full payload: {p}")
            if j["kind"] == "lyric_understanding" and not allow:
                print("  NOTE: a real run is blocked without --allow-lyrics-upload")
        return 0

    try:
        client = make_client(cfg, model)
    except MetaApiError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    workers = max(1, int(getattr(args, "workers", None) or 1))
    failures = 0

    def report(j: dict[str, Any], status: str, result: Any) -> None:
        nonlocal failures
        if status == "cached":
            print(f"cached {j['id']} (review={result['review']['status']})", flush=True)
        elif status == "failed":
            failures += 1
            print(f"FAILED {j['id']}: {result}", file=sys.stderr, flush=True)
        else:
            flags = result["validation"]["lint_flags"]
            flag = f", {len(flags)} lint flag(s) for review" if flags else ""
            print(f"{'OK' if status == 'ok' else 'INVALID'} {j['id']} ({result['attempts'][-1].get('latency_seconds')}s{flag})", flush=True)
            if status != "ok":
                failures += 1

    if workers == 1:
        for j in jobs:
            report(j, *execute_job(cfg, client, j, model, args.force))
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_job, cfg, client, j, model, args.force): j for j in jobs}
            for fut in as_completed(futures):
                report(futures[fut], *fut.result())
    from ..export.build import write_interpretations

    write_interpretations(cfg)
    return 1 if failures else 0
