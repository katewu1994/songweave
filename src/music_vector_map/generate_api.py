"""On-demand pair explanations for the local page (used by `mvm serve`).

Opening the page never calls the API. A request is sent only after the user clicks Generate, sees the
preview of exactly what will be sent, and confirms; the confirmation must name the previewed job.
Only audio-relation numbers and track IDs are sent (no lyrics, titles, audio or vectors). The API key
stays in this process and is never returned to the browser.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from .config import Config
from .interpretations.cache import find
from .interpretations.client import MetaApiError, read_api_key, refuse_training_models
from .interpretations.jobs import execute_job, make_client, prepare_job
from .interpretations.prompts import MissingPromptError, has_prompt

LANGS = ("en", "ja")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class GenerateApi:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._running: set[str] = set()

    # --------------------------------------------------------------- helpers
    def _meta(self) -> dict[str, Any]:
        return self.cfg.section("meta_api")

    def _export(self) -> dict[str, Any]:
        return json.loads((self.cfg.export_dir / "export.json").read_text(encoding="utf-8"))

    def _job(self, body: dict[str, Any]) -> dict[str, Any]:
        a, b, lang = body.get("a"), body.get("b"), body.get("lang", "en")
        if not isinstance(a, str) or not isinstance(b, str) or a == b:
            raise ApiError(400, "need two different track IDs")
        if lang not in LANGS:
            raise ApiError(400, f"lang must be one of {LANGS}")
        export = self._export()
        ids = {t["track_id"] for t in export["tracks"]}
        if a not in ids or b not in ids:
            raise ApiError(404, "unknown track")
        model = self._meta()["model"]
        refuse_training_models(model)
        try:
            return prepare_job(self.cfg, export, "pair_explanation", (a, b), False, lang, model)
        except MissingPromptError as exc:
            raise ApiError(503, str(exc)) from exc

    # --------------------------------------------------------------- endpoints
    def status(self) -> dict[str, Any]:
        meta = self._meta()
        available = (
            bool(meta.get("enabled"))
            and has_prompt(self.cfg, "pair_explanation")
            and bool(read_api_key(self.cfg.root, list(meta["key_env"])))
        )
        return {"available": available, "model": meta["model"], "langs": list(LANGS)}

    def preview(self, body: dict[str, Any]) -> dict[str, Any]:
        j = self._job(body)
        cached = find(self.cfg, j["id"])
        return {"job_id": j["id"], "cached": bool(cached and cached["validation"]["status"] == "pass"), "model": self._meta()["model"], "scope": j["scope"]}

    def generate(self, body: dict[str, Any]) -> dict[str, Any]:
        j = self._job(body)
        if body.get("confirm_job_id") != j["id"]:
            raise ApiError(409, "confirmation does not match the previewed job; preview again")
        with self._lock:
            if j["id"] in self._running:
                raise ApiError(409, "this job is already running")
            self._running.add(j["id"])
        try:
            try:
                client = make_client(self.cfg, self._meta()["model"])
            except MetaApiError as e:
                raise ApiError(503, str(e)) from e
            status, result = execute_job(self.cfg, client, j, self._meta()["model"])
        finally:
            with self._lock:
                self._running.discard(j["id"])
        from .export.build import write_interpretations

        write_interpretations(self.cfg)
        if status == "failed":
            raise ApiError(502, f"generation failed: {result}")
        rec = result if isinstance(result, dict) else {}
        return {"status": status, "interpretation_id": rec.get("interpretation_id"), "validation": rec.get("validation", {}).get("status")}
