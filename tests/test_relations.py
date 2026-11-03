import numpy as np

from music_vector_map.relations.compute import ViewSpace, l2n, least_matched, top_unit_pairs, track_vector


def test_track_vector_is_mean_of_normalised_units():
    u = np.array([[3.0, 0.0], [0.0, 1.0]])
    v = track_vector(u)
    assert np.allclose(v, l2n(np.array([1.0, 1.0])))


def _space(vecs, ids=None):
    vecs = l2n(np.asarray(vecs, dtype=float))
    ids = ids or [f"t{i}" for i in range(len(vecs))]
    return ViewSpace("overall_peav", "peav_audio", ids, vecs)


def test_neighbours_come_from_original_space_not_2d():
    # 4-D space where the PCA projection can disagree with true cosine neighbours.
    rng = np.random.default_rng(1)
    vecs = rng.normal(size=(8, 6))
    vs = _space(vecs)
    coords, _ = vs.pca2()
    for a in vs.track_ids:
        expected = sorted((t for t in vs.track_ids if t != a), key=lambda t: (-vs.score(a, t), t))
        assert [n["track_id"] for n in vs.neighbors(a, 7)] == expected
    assert all(-1.0 <= c <= 1.0 for xy in coords.values() for c in xy)


def test_ranks_are_consistent():
    vs = _space([[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0], [0, 0, 1]])
    assert vs.rank_of("t0", "t1") == 1
    pr = vs.pair_ranks()
    assert pr[("t0", "t1")] == 1 and len(pr) == 6


def test_pca_orientation_deterministic():
    rng = np.random.default_rng(2)
    vecs = rng.normal(size=(6, 5))
    c1, _ = _space(vecs).pca2()
    c2, _ = _space(vecs.copy()).pca2()
    assert c1 == c2


def test_top_unit_pairs_do_not_overlap():
    S = np.array([[0.9, 0.8, 0.1], [0.85, 0.7, 0.2], [0.1, 0.2, 0.95]])
    spans = [(0, 30), (15, 45), (30, 60)]
    picks = top_unit_pairs(S, spans, spans, 3)
    assert picks[0][:2] == (2, 2)
    # second pick must not overlap window 2 on either side; (0,0)/(0,1)/(1,0) overlap? (0,30)&(30,60) do not overlap
    for i, (a1, b1, _) in enumerate(picks):
        for a2, b2, _ in picks[i + 1 :]:
            assert a1 != a2 and b1 != b2


def test_least_matched_each_side():
    S = np.array([[0.9, 0.1], [0.2, 0.3]])
    assert least_matched(S, 0) == (1, 0.3)
    assert least_matched(S, 1) == (1, 0.3)
