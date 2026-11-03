"""`mvm analyze`: local model inference only. Never calls a generation API.

Backends run sequentially (one heavy model loaded at a time) and each loaded model is reused for
every window of every selected track.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .audio.decode import decode_mono, probe
from .audio.windows import Window, coverage, mark_windows, plan_windows
from .config import Config, file_sha256, stable_hash
from .lyrics.blocks import block_lang, read_lyrics, split_blocks, text_sha256
from .manifest import Manifest, Track
from .schemas import LYRICS_EMBEDDABLE, MERIT_HEADS, VIEW_SPACE
from .store import is_current, read_meta, write_record
from .workers import run_worker, temp_dir, worker_model_info

BACKENDS = ("peav", "merit", "sonar")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Analyzer:
    def __init__(self, cfg: Config, manifest: Manifest, log: Callable[[str], None] = print, force: bool = False, device: str | None = None):
        self.cfg = cfg
        self.manifest = manifest
        self.log = log
        self.force = force
        self.device = device or cfg.section("analysis")["device"]
        self.silence = float(cfg.section("analysis")["silence_dbfs"])
        self.timings: list[dict[str, Any]] = []
        self._sha: dict[str, str] = {}
        self._probe: dict[str, dict] = {}

    # ------------------------------------------------------------------ helpers
    def audio_sha(self, t: Track) -> str:
        if t.track_id not in self._sha:
            self._sha[t.track_id] = file_sha256(t.audio_path)
        return self._sha[t.track_id]

    def audio_probe(self, t: Track) -> dict:
        if t.track_id not in self._probe:
            self._probe[t.track_id] = probe(t.audio_path)
        return self._probe[t.track_id]

    def _base_meta(self, t: Track, view_id: str, settings: dict, windows: list[Window], analyzed: list[int], model_info: dict, elapsed: float) -> dict:
        p = self.audio_probe(t)
        return {
            "view_id": view_id,
            "unit": "window",
            "input_sha256": self.audio_sha(t),
            "input_probe": p,
            "duration_seconds": p["duration_seconds"],
            "settings": settings,
            "settings_hash": stable_hash(settings),
            "model_info": model_info,
            "windows": [w.to_dict() for w in windows],
            "analyzed_unit_ids": analyzed,
            "coverage": coverage(windows, set(analyzed)),
            "elapsed_seconds": round(elapsed, 3),
            "created_at": now_iso(),
        }

    # ------------------------------------------------------------------ PE-AV
    def run_peav(self, tracks: list[Track]) -> None:
        bc = self.cfg.section("backends", "overall_peav")
        settings = {
            "backend": "peav",
            "model": bc["model"],
            "revision": bc["revision"],
            "sample_rate": bc["sample_rate"],
            "window_seconds": bc["window_seconds"],
            "hop_seconds": bc["hop_seconds"],
            "silence_dbfs": self.silence,
            "aggregation_input": "audio_embeds (audio_head(pooler_output))",
        }
        sh = stable_hash(settings)
        todo = [t for t in tracks if self.force or not is_current(read_meta(self.cfg.analysis_dir, "peav_audio", t.track_id), self.audio_sha(t), sh)]
        self.log(f"PE-AV: {len(todo)} of {len(tracks)} track(s) need analysis")
        if not todo:
            return
        from .audio.peav import PeavBackend

        backend = PeavBackend(bc["model"], bc["revision"], int(bc["sample_rate"]), device=self.device)
        self.log(f"  [peav] model loaded in {backend.load_seconds:.1f}s")
        for t in todo:
            t0 = time.perf_counter()
            mono, sr = decode_mono(t.audio_path, int(bc["sample_rate"]))
            dur = mono.shape[0] / sr
            windows = mark_windows(mono, sr, plan_windows(dur, float(bc["window_seconds"]), float(bc["hop_seconds"])), self.silence)
            t1 = time.perf_counter()
            ids, emb = backend.embed_windows(mono, windows)
            infer = time.perf_counter() - t1
            elapsed = time.perf_counter() - t0
            meta = self._base_meta(t, "overall_peav", settings, windows, ids, backend.model_info, elapsed)
            meta["padded_input_seconds"] = 0.0
            write_record(self.cfg.analysis_dir, "peav_audio", t.track_id, meta, ids, emb)
            self.timings.append({"backend": "peav", "track_id": t.track_id, "audio_seconds": round(dur, 2), "windows": len(ids), "inference_seconds": round(infer, 2), "total_seconds": round(elapsed, 2)})
            self.log(f"  [peav] {t.track_id} {dur:6.1f}s audio, {len(ids)} windows, {elapsed:5.1f}s")
        del backend

    # ------------------------------------------------------------------ MERIT
    def run_merit(self, tracks: list[Track]) -> None:
        bc = self.cfg.section("backends", "merit")
        settings = {
            "backend": "merit",
            "backbone": bc["backbone"],
            "backbone_revision": bc["backbone_revision"],
            "heads_repo": bc["heads_repo"],
            "heads_revision": bc["heads_revision"],
            "layers": list(bc["layers"]),
            "sample_rate": bc["sample_rate"],
            "window_seconds": bc["window_seconds"],
            "hop_seconds": bc["hop_seconds"],
            "silence_dbfs": self.silence,
        }
        sh = stable_hash(settings)

        def current(t: Track) -> bool:
            return all(is_current(read_meta(self.cfg.analysis_dir, VIEW_SPACE[v], t.track_id), self.audio_sha(t), sh) for v in MERIT_HEADS)

        todo = [t for t in tracks if self.force or not current(t)]
        self.log(f"MERIT: {len(todo)} of {len(tracks)} track(s) need analysis")
        if not todo:
            return
        sr = int(bc["sample_rate"])
        tmp = temp_dir(self.cfg)
        plans: dict[str, list[Window]] = {}
        job_tracks = []
        for t in todo:
            mono, _ = decode_mono(t.audio_path, sr)
            dur = mono.shape[0] / sr
            windows = mark_windows(mono, sr, plan_windows(dur, float(bc["window_seconds"]), float(bc["hop_seconds"])), self.silence)
            plans[t.track_id] = windows
            job_tracks.append(
                {
                    "track_id": t.track_id,
                    "audio_path": str(t.audio_path),
                    "windows": [[w.index, w.start, w.end] for w in windows if not w.silent],
                    "out_npz": str(tmp / f"merit_{t.track_id}.npz"),
                }
            )
        job = {k: settings[k] for k in ("backbone", "backbone_revision", "heads_repo", "heads_revision", "layers", "sample_rate", "window_seconds")}
        job.update(device=self.device, tracks=job_tracks)
        t0 = time.perf_counter()
        events = run_worker(self.cfg, "merit", bc["python"], job, self.log)
        model_info = worker_model_info(events)
        per_track = {e["track_id"]: e["seconds"] for e in events if e.get("event") == "track_done"}
        for jt in job_tracks:
            tid = jt["track_id"]
            t = self.manifest.by_id()[tid]
            with np.load(jt["out_npz"]) as z:
                ids = [int(i) for i in z["unit_ids"]]
                padded = float(z["padded_seconds"].max()) if z["padded_seconds"].size else 0.0
                factors = {f: z[f] for f in ("melody", "rhythm", "timbre")}
            for view, head in MERIT_HEADS.items():
                factor = {"head_mel": "melody", "head_rhy": "rhythm", "head_tim": "timbre"}[head]
                info = dict(model_info, head=factor, head_info=model_info["heads"][factor])
                info.pop("heads", None)
                meta = self._base_meta(t, view, settings, plans[tid], ids, info, per_track.get(tid, 0.0))
                meta["padded_input_seconds"] = padded
                write_record(self.cfg.analysis_dir, VIEW_SPACE[view], tid, meta, ids, factors[factor])
            Path(jt["out_npz"]).unlink(missing_ok=True)
            dur = self.audio_probe(t)["duration_seconds"]
            self.timings.append({"backend": "merit", "track_id": tid, "audio_seconds": round(dur, 2), "windows": len(ids), "inference_seconds": per_track.get(tid), "total_seconds": per_track.get(tid)})
        self.log(f"  [merit] job finished in {time.perf_counter() - t0:.1f}s")

    # ------------------------------------------------------------------ SONAR
    def run_sonar(self, tracks: list[Track]) -> None:
        bc = self.cfg.section("backends", "lyrics_sonar")
        eligible = [t for t in tracks if t.lyrics.status in LYRICS_EMBEDDABLE]
        skipped = len(tracks) - len(eligible)
        self.log(f"SONAR: {len(eligible)} track(s) with available lyrics; {skipped} without verified text (not scored as zero)")
        tmp = temp_dir(self.cfg)
        items, prepared = [], {}
        for t in eligible:
            text = read_lyrics(t.lyrics_path)  # type: ignore[arg-type]
            blocks = split_blocks(text, int(bc["max_lines_per_block"]))
            lang = t.lyrics.lang or bc["default_lang"]
            settings = {"backend": "sonar", "encoder": bc["encoder"], "lang": lang, "max_lines_per_block": bc["max_lines_per_block"], "per_block_lang": "latin-only blocks -> eng_Latn"}
            sha = text_sha256(text)
            if not self.force and is_current(read_meta(self.cfg.analysis_dir, "sonar_text", t.track_id), sha, stable_hash(settings)):
                continue
            if not blocks:
                self.log(f"  [sonar] {t.track_id}: lyrics file has no text; mark it no_lyrics_confirmed or fix the file")
                continue
            prepared[t.track_id] = (blocks, settings, sha)
            items.append(
                {
                    "track_id": t.track_id,
                    "lang": lang,
                    "blocks": [{"index": b.index, "text": b.text, "lang": block_lang(b.text, lang)} for b in blocks],
                    "out_npz": str(tmp / f"sonar_{t.track_id}.npz"),
                }
            )
        if not items:
            return
        events = run_worker(self.cfg, "sonar", bc["python"], {"encoder": bc["encoder"], "device": "cpu", "items": items}, self.log)
        model_info = worker_model_info(events)
        per_track = {e["track_id"]: e["seconds"] for e in events if e.get("event") == "track_done"}
        for it in items:
            tid = it["track_id"]
            blocks, settings, sha = prepared[tid]
            with np.load(it["out_npz"]) as z:
                ids, emb = [int(i) for i in z["unit_ids"]], z["embeddings"]
            meta = {
                "view_id": "lyrics_sonar",
                "unit": "lyric_block",
                "input_sha256": sha,
                "settings": settings,
                "settings_hash": stable_hash(settings),
                "model_info": model_info,
                "blocks": [{"index": b.index, "text": b.text, "line_start": b.line_start, "line_end": b.line_end, "lang": block_lang(b.text, settings["lang"])} for b in blocks],
                "analyzed_unit_ids": ids,
                "coverage": "full" if len(ids) == len(blocks) else "partial",
                "lyrics_status": "available",
                "elapsed_seconds": per_track.get(tid),
                "created_at": now_iso(),
            }
            write_record(self.cfg.analysis_dir, "sonar_text", tid, meta, ids, emb)
            Path(it["out_npz"]).unlink(missing_ok=True)

    # ------------------------------------------------------------------ entry
    def run(self, track_ids: list[str] | None, backends: tuple[str, ...] = BACKENDS) -> dict[str, Any]:
        by_id = self.manifest.by_id()
        ids = track_ids or [t.track_id for t in self.manifest.tracks]
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise KeyError(f"unknown track_id(s): {unknown}")
        tracks = [by_id[i] for i in ids]
        started = time.perf_counter()
        for b in backends:
            if b == "peav":
                self.run_peav(tracks)
            elif b == "merit":
                self.run_merit(tracks)
            elif b == "sonar":
                self.run_sonar(tracks)
            else:
                raise ValueError(f"unknown backend {b}")
        summary = {
            "created_at": now_iso(),
            "device": self.device,
            "backends": list(backends),
            "track_ids": ids,
            "wall_seconds": round(time.perf_counter() - started, 2),
            "timings": self.timings,
        }
        logs = self.cfg.artifacts_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"analyze_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
