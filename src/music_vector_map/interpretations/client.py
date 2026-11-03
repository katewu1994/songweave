"""Minimal Meta Model API client (OpenAI-compatible chat completions with strict JSON schema).

The API key is read from the environment or the repository .env file and is never logged.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class MetaApiError(RuntimeError):
    pass


def refuse_training_models(model: str) -> None:
    # "*-contributor" variants let Meta use prompts and completions for training.
    if "contributor" in model.lower():
        raise MetaApiError(f"model {model!r} permits training on submitted content; refusing to send user data")


def read_api_key(root: Path, names: list[str]) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    env = root / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m and m.group(1) in names and m.group(2).strip():
                return m.group(2).strip().strip('"').strip("'")
    return None


@dataclass
class Completion:
    content: str | None
    finish_reason: str | None
    response_id: str | None
    model: str | None
    usage: dict[str, Any]
    latency_seconds: float


class MetaClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 240.0, max_completion_tokens: int = 12000):
        refuse_training_models(model)
        if not api_key:
            raise MetaApiError("no Meta API key configured (META_API_KEY or MODEL_API_KEY)")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self.timeout = timeout
        self.max_completion_tokens = max_completion_tokens

    def list_models(self) -> list[str]:
        r = httpx.get(f"{self.base_url}/models", headers=self._headers, timeout=30)
        if r.status_code != 200:
            raise MetaApiError(f"GET /models -> HTTP {r.status_code}")
        return [m["id"] for m in r.json().get("data", [])]

    def chat_json(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> Completion:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "max_completion_tokens": self.max_completion_tokens,
        }
        last: Exception | None = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", headers=self._headers, json=body, timeout=self.timeout)
            except httpx.HTTPError as e:
                last = MetaApiError(f"network error: {type(e).__name__}")
                time.sleep(2 * (attempt + 1))
                continue
            latency = time.perf_counter() - t0
            if r.status_code in (429, 500, 502, 503, 504):
                last = MetaApiError(f"HTTP {r.status_code}")
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                msg = r.text[:300].replace(self._headers["Authorization"], "[redacted]")
                raise MetaApiError(f"HTTP {r.status_code}: {msg}")
            d = r.json()
            ch = (d.get("choices") or [{}])[0]
            return Completion(
                content=(ch.get("message") or {}).get("content"),
                finish_reason=ch.get("finish_reason"),
                response_id=d.get("id"),
                model=d.get("model"),
                usage=d.get("usage") or {},
                latency_seconds=round(latency, 2),
            )
        raise last or MetaApiError("request failed")
