"""Relations inside one view's own embedding space.

Track vector = L2-normalised mean of L2-normalised unit (window / lyric block) vectors.
Neighbours and pair scores are cosine similarities in that original space; 2-D coordinates are
a PCA projection for display only and are never used to rank neighbours.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def l2n(x: np.ndarray, axis: int = -1) -> np.ndarray:
    n = np.linalg.norm(x, axis=axis, keepdims=True)
    if np.any(n == 0):
        raise ValueError("zero-norm vector")
    return x / n


def track_vector(unit_embeddings: np.ndarray) -> np.ndarray:
    if unit_embeddings.shape[0] == 0:
        raise ValueError("no analysed units")
    return l2n(l2n(unit_embeddings.astype(np.float64)).mean(axis=0))


@dataclass
class ViewSpace:
    view_id: str
    space: str
    track_ids: list[str]
    vectors: np.ndarray  # (n, d) unit rows
    units: dict[str, np.ndarray] = field(default_factory=dict)  # track_id -> (k, d) unit rows
    unit_ids: dict[str, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.track_ids) != self.vectors.shape[0]:
            raise ValueError("track_ids / vectors mismatch")
        self.index = {t: i for i, t in enumerate(self.track_ids)}
        self.sim = self.vectors @ self.vectors.T

    def score(self, a: str, b: str) -> float:
        return float(self.sim[self.index[a], self.index[b]])

    def ranked(self, a: str) -> list[tuple[str, float]]:
        """All other tracks ordered by similarity to `a` (ties broken by track ID for determinism)."""
        i = self.index[a]
        others = [(t, float(self.sim[i, j])) for j, t in enumerate(self.track_ids) if j != i]
        return sorted(others, key=lambda x: (-x[1], x[0]))

    def neighbors(self, a: str, k: int) -> list[dict]:
        return [{"track_id": t, "score": round(s, 6), "rank": r + 1} for r, (t, s) in enumerate(self.ranked(a)[:k])]

    def rank_of(self, a: str, b: str) -> int:
        for r, (t, _) in enumerate(self.ranked(a)):
            if t == b:
                return r + 1
        raise KeyError(b)

    def pair_ranks(self) -> dict[tuple[str, str], int]:
        """Rank of every unordered pair among all pairs in this view (1 = most similar)."""
        n = len(self.track_ids)
        pairs = [((self.track_ids[i], self.track_ids[j]), float(self.sim[i, j])) for i in range(n) for j in range(i + 1, n)]
        pairs.sort(key=lambda x: (-x[1], x[0]))
        return {tuple(sorted(p)): r + 1 for r, (p, _) in enumerate(pairs)}  # type: ignore[misc]

    def pca2(self) -> tuple[dict[str, list[float]], list[float]]:
        n = self.vectors.shape[0]
        if n == 1:
            return {self.track_ids[0]: [0.0, 0.0]}, [1.0, 0.0]
        X = self.vectors - self.vectors.mean(axis=0, keepdims=True)
        U, S, _ = np.linalg.svd(X, full_matrices=False)
        k = min(2, S.shape[0])
        coords = U[:, :k] * S[:k]
        if k < 2:
            coords = np.hstack([coords, np.zeros((n, 2 - k))])
        # Deterministic orientation: the largest-magnitude coordinate on each axis is positive.
        for c in range(2):
            col = coords[:, c]
            if col.size and col[np.argmax(np.abs(col))] < 0:
                coords[:, c] = -col
        scale = np.abs(coords).max() or 1.0
        coords = coords / scale
        var = (S**2) / max(float((S**2).sum()), 1e-12)
        ev = [float(var[i]) if i < var.shape[0] else 0.0 for i in range(2)]
        return {t: [round(float(x), 6), round(float(y), 6)] for t, (x, y) in zip(self.track_ids, coords)}, ev


def unit_similarity(ua: np.ndarray, ub: np.ndarray) -> np.ndarray:
    return l2n(ua.astype(np.float64)) @ l2n(ub.astype(np.float64)).T


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def top_unit_pairs(S: np.ndarray, spans_a: list[tuple[float, float]] | None, spans_b: list[tuple[float, float]] | None, n: int) -> list[tuple[int, int, float]]:
    """Greedy best-matching unit pairs; later picks may not overlap earlier picks on either side."""
    order = np.dstack(np.unravel_index(np.argsort(-S, axis=None), S.shape))[0]
    chosen: list[tuple[int, int, float]] = []
    for i, j in order:
        i, j = int(i), int(j)
        clash = False
        for ci, cj, _ in chosen:
            if i == ci or j == cj:
                clash = True
            elif spans_a is not None and _overlaps(spans_a[i], spans_a[ci]):
                clash = True
            elif spans_b is not None and _overlaps(spans_b[j], spans_b[cj]):
                clash = True
            if clash:
                break
        if not clash:
            chosen.append((i, j, float(S[i, j])))
        if len(chosen) >= n:
            break
    return chosen


def least_matched(S: np.ndarray, axis: int) -> tuple[int, float]:
    """Unit on one side whose best match on the other side is weakest (a contrast candidate)."""
    best = S.max(axis=1) if axis == 0 else S.max(axis=0)
    idx = int(np.argmin(best))
    return idx, float(best[idx])
