"""SONAR worker: official Meta SONAR text encoder (sonar-space + fairseq2).

Runs inside .venvs/sonar (fairseq2n 0.8.1 requires torch 2.9.1). Started by `mvm analyze` or
`mvm probe sonar` as `python -I workers/sonar_worker.py job.json`. Lyric text is data only.

Job: {"encoder", "device", "items": [{"track_id", "lang", "blocks": [{"index", "text", "lang"?}], "out_npz"}]}
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import time

import numpy as np
import torch


def emit(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def checkpoint_info(encoder):
    import fairseq2
    import sonar

    card = os.path.join(os.path.dirname(sonar.__file__), "cards", f"{encoder}.yaml")
    uri = None
    if os.path.isfile(card):
        for line in open(card, encoding="utf-8"):
            if line.startswith("checkpoint:"):
                uri = line.split(":", 1)[1].strip().strip('"')
    sha = None
    if uri:
        cache = os.path.expanduser(os.environ.get("FAIRSEQ2_CACHE_DIR", "~/.cache/fairseq2/assets"))
        hits = glob.glob(os.path.join(cache, "*", os.path.basename(uri)))
        if hits:
            h = hashlib.sha256()
            with open(hits[0], "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            sha = h.hexdigest()
    return {
        "encoder": encoder,
        "checkpoint_uri": uri,
        "checkpoint_sha256": sha,
        "sonar_space": getattr(sonar, "__version__", None),
        "fairseq2": fairseq2.__version__,
        "torch": torch.__version__,
    }


def main(job_path):
    from sonar.inference_pipelines.text import TextToEmbeddingModelPipeline

    job = json.load(open(job_path, encoding="utf-8"))
    device = torch.device(job.get("device", "cpu"))
    t0 = time.perf_counter()
    pipe = TextToEmbeddingModelPipeline(encoder=job["encoder"], tokenizer=job["encoder"], device=device, dtype=torch.float32)
    info = checkpoint_info(job["encoder"])
    info.update(device=str(device), dtype="float32")
    emit(event="loaded", seconds=round(time.perf_counter() - t0, 2), model_info=info)
    for item in job["items"]:
        t1 = time.perf_counter()
        blocks = item["blocks"]
        arr = None
        # Each block is encoded with its own source language tag (default: the track's language).
        for lang in sorted({b.get("lang", item["lang"]) for b in blocks}):
            idx = [i for i, b in enumerate(blocks) if b.get("lang", item["lang"]) == lang]
            with torch.inference_mode():
                emb = pipe.predict([blocks[i]["text"] for i in idx], source_lang=lang, batch_size=8).float().cpu().numpy()
            if arr is None:
                arr = np.zeros((len(blocks), emb.shape[1]), np.float32)
            arr[idx] = emb
        np.savez(item["out_npz"], unit_ids=np.asarray([b["index"] for b in blocks], np.int64), embeddings=arr)
        emit(event="track_done", track_id=item["track_id"], blocks=len(blocks), seconds=round(time.perf_counter() - t1, 2))
    emit(event="done", seconds=round(time.perf_counter() - t0, 2))


if __name__ == "__main__":
    main(sys.argv[1])
