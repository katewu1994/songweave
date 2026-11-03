"""Run an isolated-environment worker (workers/*.py) as a plain subprocess and stream its JSON events."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import Config


class WorkerError(RuntimeError):
    pass


def run_worker(cfg: Config, name: str, python: str, job: dict[str, Any], log: Callable[[str], None]) -> list[dict[str, Any]]:
    interp = cfg.path(python)
    script = cfg.root / "workers" / f"{name}_worker.py"
    if not interp.exists():
        raise WorkerError(f"{name}: interpreter {interp} not found; run scripts/setup_envs.sh")
    env = dict(os.environ)
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    if name == "sonar":
        # fairseq2n's macOS wheel links libsndfile from Homebrew; setup_envs.sh places the copy
        # bundled with the soundfile wheel next to the environment instead.
        env["DYLD_FALLBACK_LIBRARY_PATH"] = str(interp.parent.parent / "lib")
    events: list[dict[str, Any]] = []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
        job_path = f.name
    try:
        proc = subprocess.Popen(
            [str(interp), "-I", str(script), job_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(cfg.root),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if ev.get("event") == "track_done":
                log(f"  [{name}] {ev['track_id']} done in {ev['seconds']}s")
            elif ev.get("event") == "loaded":
                log(f"  [{name}] model loaded in {ev['seconds']}s")
        stderr = proc.stderr.read() if proc.stderr else ""
        rc = proc.wait()
    finally:
        os.unlink(job_path)
    if rc != 0:
        tail = "\n".join(stderr.strip().splitlines()[-15:])
        raise WorkerError(f"{name} worker exited with {rc}:\n{tail}")
    return events


def worker_model_info(events: list[dict[str, Any]]) -> dict[str, Any]:
    for ev in events:
        if ev.get("event") == "loaded":
            return ev["model_info"]
    raise WorkerError("worker did not report model_info")


def temp_dir(cfg: Config) -> Path:
    d = cfg.artifacts_dir / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d
