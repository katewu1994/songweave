"""`mvm probe meta|sonar`: checks that use only fixed non-song text."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from .config import Config

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}},
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}

SONAR_PROBE = [
    ("eng_Latn", "The weather is pleasant today."),
    ("jpn_Jpan", "今日は天気がいいです。"),
    ("eng_Latn", "I need to fix the printer before the meeting."),
]


def _write(cfg: Config, name: str, result: dict) -> None:
    d = cfg.artifacts_dir / "logs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"probe_{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def run_probe(cfg: Config, target: str) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if target == "meta":
        from .interpretations.client import MetaApiError, MetaClient, read_api_key

        meta = cfg.section("meta_api")
        key = read_api_key(cfg.root, list(meta["key_env"]))
        if not key:
            print("BLOCKED: no API key")
            return 2
        client = MetaClient(meta["base_url"], key, meta["model"], 120, 2000)
        result: dict = {"checked_at": now, "base_url": meta["base_url"], "model": meta["model"], "content": "fixed non-song question"}
        try:
            models = client.list_models()
            result["model_listed"] = meta["model"] in models
            comp = client.chat_json("Return only JSON matching the schema.", "What is the capital of France? Keep it short.", "probe", PROBE_SCHEMA)
            parsed = json.loads(comp.content or "null")
            ok = isinstance(parsed, dict) and set(parsed) == {"answer", "confidence"}
            result.update(status="PASS" if ok else "FAIL", structured_output=ok, finish_reason=comp.finish_reason, latency_seconds=comp.latency_seconds, response_model=comp.model, usage=comp.usage)
        except (MetaApiError, json.JSONDecodeError) as e:
            result.update(status="FAIL", error=str(e))
        _write(cfg, "meta", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1

    from .workers import run_worker, temp_dir, worker_model_info

    bc = cfg.section("backends", "lyrics_sonar")
    tmp = temp_dir(cfg)
    items = [{"track_id": f"probe{i}", "lang": lang, "blocks": [{"index": 0, "text": text}], "out_npz": str(tmp / f"probe{i}.npz")} for i, (lang, text) in enumerate(SONAR_PROBE)]
    events = run_worker(cfg, "sonar", bc["python"], {"encoder": bc["encoder"], "device": "cpu", "items": items}, print)
    vecs = []
    for it in items:
        with np.load(it["out_npz"]) as z:
            vecs.append(z["embeddings"][0])
    V = np.stack(vecs)
    V = V / np.linalg.norm(V, axis=1, keepdims=True)
    S = V @ V.T
    ok = S[0, 1] > S[0, 2] and S[0, 1] > S[1, 2]
    result = {
        "checked_at": now,
        "status": "PASS" if ok else "FAIL",
        "model_info": worker_model_info(events),
        "dim": int(V.shape[1]),
        "cos_en_ja_same_meaning": round(float(S[0, 1]), 4),
        "cos_en_unrelated": round(float(S[0, 2]), 4),
        "cos_ja_unrelated": round(float(S[1, 2]), 4),
    }
    _write(cfg, "sonar", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1
