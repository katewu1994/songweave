"""Full-song window plans and silence marking.

Windows tile the whole decoded song. The final window is anchored to the song end instead of being
zero-padded, so every window's [start, end) is real playback time. A song shorter than one window
gets a single window covering the whole song; any padding a backend adds is recorded separately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class Window:
    index: int
    start: float
    end: float
    rms_dbfs: float
    silent: bool

    def to_dict(self) -> dict:
        return asdict(self)


def plan_windows(duration: float, window: float, hop: float) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    if hop <= 0 or window <= 0 or hop > window:
        raise ValueError("require 0 < hop <= window")
    if duration <= window:
        return [(0.0, float(duration))]
    starts: list[float] = []
    s = 0.0
    while s + window <= duration + 1e-9:
        starts.append(s)
        s += hop
    if starts[-1] + window < duration - 1e-6:
        starts.append(duration - window)
    return [(round(st, 6), round(min(st + window, duration), 6)) for st in starts]


def rms_dbfs(x: np.ndarray) -> float:
    if x.size == 0:
        return -200.0
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return float(20.0 * np.log10(max(rms, 1e-10)))


def mark_windows(mono: np.ndarray, sr: int, spans: list[tuple[float, float]], silence_dbfs: float) -> list[Window]:
    out = []
    for i, (a, b) in enumerate(spans):
        seg = mono[int(round(a * sr)) : int(round(b * sr))]
        level = rms_dbfs(seg)
        out.append(Window(index=i, start=a, end=b, rms_dbfs=round(level, 2), silent=bool(level < silence_dbfs)))
    return out


def coverage(windows: list[Window], analyzed: set[int]) -> str:
    """'full' when every declared non-silent window was analyzed, else 'partial' (or 'missing')."""
    required = {w.index for w in windows if not w.silent}
    if not required:
        return "missing"
    if required <= analyzed:
        return "full"
    return "partial" if analyzed & required else "missing"
