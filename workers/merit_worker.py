"""MERIT worker: MERT-v1-330M backbone + three trained MERIT projection heads (melody, rhythm, timbre).

Runs inside .venvs/merit (transformers 4.x, required by MERT's remote code). Started by
`mvm analyze` as `python -I workers/merit_worker.py job.json`; it does not import the main package.
The backbone is loaded once and reused for every window of every track in the job.

Follows the reference inference in AMAAI-Lab/MERIT README (commit aa0039b): 24 kHz mono, layers
(3, 4, 5, 6, 23) mean-pooled over time and concatenated to 5120-d, each head -> 128-d unit vector.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from math import gcd

import numpy as np
import soundfile as sf
import torch
import torch.nn as nn
import torch.nn.functional as F
from huggingface_hub import hf_hub_download
from scipy.signal import resample_poly
from transformers import AutoModel, Wav2Vec2FeatureExtractor

HEADS = {"melody": "head_mel", "rhythm": "head_rhy", "timbre": "head_tim"}


class ProjectionHead(nn.Module):
    def __init__(self, in_dim=5120, hidden_dim=512, out_dim=128):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.ReLU(inplace=True), nn.Linear(hidden_dim, out_dim, bias=False))

    def forward(self, x):
        return F.normalize(self.net(x), dim=-1)


def emit(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_heads(repo, revision, device):
    heads, info = {}, {}
    for factor, name in HEADS.items():
        path = hf_hub_download(repo, f"{name}/best_head.pt", revision=revision)
        ckpt = torch.load(path, map_location=device, weights_only=True)
        head = ProjectionHead(ckpt["in_dim"], ckpt["hidden_dim"], ckpt["out_dim"])
        head.load_state_dict(ckpt["state_dict"])  # strict: all three trained heads must load
        heads[factor] = head.to(device).eval()
        info[factor] = {
            "file": f"{name}/best_head.pt",
            "sha256": sha256_file(path),
            "trained_backbone": ckpt.get("model_id"),
            "encoder": ckpt.get("encoder"),
            "epoch": ckpt.get("epoch"),
            "val_acc": ckpt.get("val_acc"),
            "dims": [ckpt["in_dim"], ckpt["hidden_dim"], ckpt["out_dim"]],
        }
    # Three distinct heads, not one vector reused three times.
    w = [heads[f].net[0].weight.detach() for f in HEADS]
    if torch.equal(w[0], w[1]) or torch.equal(w[1], w[2]) or torch.equal(w[0], w[2]):
        raise RuntimeError("MERIT heads are not distinct")
    return heads, info


def decode(path, sr):
    data, orig = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if orig != sr:
        g = gcd(orig, sr)
        mono = resample_poly(mono, sr // g, orig // g).astype(np.float32)
    return mono


def main(job_path):
    job = json.load(open(job_path, encoding="utf-8"))
    device = torch.device(job.get("device", "cpu"))
    torch.set_grad_enabled(False)
    t0 = time.perf_counter()
    mert, loading = AutoModel.from_pretrained(
        job["backbone"], revision=job["backbone_revision"], trust_remote_code=True, output_loading_info=True
    )
    problems = {k: v for k, v in loading.items() if v}
    if problems:
        raise RuntimeError(f"MERT weights did not load cleanly: {problems}")
    mert = mert.float().to(device).eval()
    processor = Wav2Vec2FeatureExtractor.from_pretrained(job["backbone"], revision=job["backbone_revision"], trust_remote_code=True)
    sr = int(job["sample_rate"])
    if processor.sampling_rate != sr:
        raise RuntimeError(f"MERT expects {processor.sampling_rate} Hz")
    heads, head_info = load_heads(job["heads_repo"], job["heads_revision"], device)
    layers = tuple(job["layers"])
    win_samples = int(round(float(job["window_seconds"]) * sr))
    import transformers

    emit(
        event="loaded",
        seconds=round(time.perf_counter() - t0, 2),
        model_info={
            "backbone": job["backbone"],
            "backbone_revision": job["backbone_revision"],
            "heads_repo": job["heads_repo"],
            "heads_revision": job["heads_revision"],
            "heads": head_info,
            "layers": list(layers),
            "transformers": transformers.__version__,
            "torch": torch.__version__,
            "device": str(device),
            "dtype": "float32",
        },
    )
    for tr in job["tracks"]:
        t1 = time.perf_counter()
        mono = decode(tr["audio_path"], sr)
        ids, padded, out = [], [], {f: [] for f in HEADS}
        for idx, start, end in tr["windows"]:
            seg = mono[int(round(start * sr)) : int(round(end * sr))]
            pad = 0
            if seg.shape[0] < win_samples:
                # Reference MERIT input is a fixed 30 s clip; padding is model input only, never playback time.
                pad = win_samples - seg.shape[0]
                seg = np.pad(seg, (0, pad))
            inputs = processor(seg, sampling_rate=sr, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            hs = mert(**inputs, output_hidden_states=True).hidden_states
            backbone = torch.cat([hs[l].mean(dim=1) for l in layers], dim=-1)
            for f, head in heads.items():
                out[f].append(head(backbone)[0].float().cpu().numpy())
            ids.append(idx)
            padded.append(pad / sr)
        np.savez(
            tr["out_npz"],
            unit_ids=np.asarray(ids, np.int64),
            padded_seconds=np.asarray(padded, np.float32),
            **{f: np.stack(v).astype(np.float32) for f, v in out.items()},
        )
        emit(event="track_done", track_id=tr["track_id"], windows=len(ids), seconds=round(time.perf_counter() - t1, 2))
    emit(event="done", seconds=round(time.perf_counter() - t0, 2))


if __name__ == "__main__":
    main(sys.argv[1])
