"""Read-only audio decoding. The decoded timeline (sample 0 = 0.0 s) is the time base for all excerpts."""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def decode_mono(path: Path, target_sr: int | None = None) -> tuple[np.ndarray, int]:
    """Decode to float32 mono (channel mean). Resamples with a polyphase filter when target_sr is given."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if target_sr is not None and sr != target_sr:
        g = gcd(sr, target_sr)
        mono = resample_poly(mono, target_sr // g, sr // g).astype(np.float32)
        sr = target_sr
    return np.ascontiguousarray(mono, dtype=np.float32), sr


def probe(path: Path) -> dict:
    info = sf.info(str(path))
    return {
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
        "duration_seconds": info.frames / info.samplerate,
        "format": info.format,
        "subtype": info.subtype,
    }
