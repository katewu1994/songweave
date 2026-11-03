"""Meta PE-AV (facebook/pe-av-small), audio-only branch, via transformers' PeAudioVideoModel."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .windows import Window


class PeavBackend:
    def __init__(self, model_id: str, revision: str, sample_rate: int, device: str = "cpu"):
        import torch
        from transformers import PeAudioFeatureExtractor, PeAudioVideoModel

        self.torch = torch
        self.device = torch.device(device)
        t0 = time.perf_counter()
        # The checkpoint's video tower has head shapes that transformers 5 re-initialises; the audio
        # tower must load exactly, which is asserted below. Only the audio branch is ever called.
        model, info = PeAudioVideoModel.from_pretrained(
            model_id, revision=revision, ignore_mismatched_sizes=True, output_loading_info=True, dtype=torch.float32
        )
        bad = [
            k
            for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
            for k in info.get(key, [])
            if "audio" in str(k)
        ]
        if bad:
            raise RuntimeError(f"PE-AV audio weights did not load cleanly: {bad[:5]}")
        self.model = model.to(self.device).eval()
        self.extractor = PeAudioFeatureExtractor.from_pretrained(model_id, revision=revision)
        if self.extractor.sampling_rate != sample_rate:
            raise RuntimeError(f"PE-AV expects {self.extractor.sampling_rate} Hz, config says {sample_rate}")
        self.sample_rate = sample_rate
        self.load_seconds = time.perf_counter() - t0
        self.model_info: dict[str, Any] = {
            "model": model_id,
            "revision": revision,
            "library": "transformers.PeAudioVideoModel.get_audio_embeds",
            "dtype": "float32",
            "device": str(self.device),
            "video_tower_reinitialised_keys": [str(k) for k in info.get("mismatched_keys", [])],
        }

    def embed_windows(self, mono: np.ndarray, windows: list[Window]) -> tuple[list[int], np.ndarray]:
        torch = self.torch
        ids, vecs = [], []
        for w in windows:
            if w.silent:
                continue
            seg = mono[int(round(w.start * self.sample_rate)) : int(round(w.end * self.sample_rate))]
            inputs = self.extractor(seg, sampling_rate=self.sample_rate, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                emb = self.model.get_audio_embeds(**inputs)
            vecs.append(emb[0].float().cpu().numpy())
            ids.append(w.index)
        dim = vecs[0].shape[0] if vecs else 0
        return ids, np.stack(vecs) if vecs else np.zeros((0, dim), np.float32)
