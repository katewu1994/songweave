import { describe, expect, it } from "vitest";
import { buildEvidenceIndex, mmss, orient, pairKey, pickInterpretations } from "./data";
import { DICTS, reasonText } from "./i18n";
import type { ExportData, PairEntry } from "./types";

// FIXTURE data for software tests only.
const entry: PairEntry = {
  a: "t_a",
  b: "t_b",
  views: {
    overall_peav: {
      available: true,
      relation_id: "rel:overall_peav:t_a:t_b",
      score: 0.8,
      rank_b_for_a: 2,
      rank_a_for_b: 5,
      n_candidates: 19,
      pair_rank: 10,
      n_pairs: 190,
      excerpts: [{ id: "exc:overall_peav:t_a:t_b:0", kind: "similar_excerpt", score: 0.9, a: { track_id: "t_a", start: 10, end: 20 }, b: { track_id: "t_b", start: 30, end: 40 } }],
      contrasts: [{ id: "con:overall_peav:t_a:t_b:t_a", kind: "contrast_excerpt", best_match_score: 0.2, segment: { track_id: "t_a", start: 0, end: 10 } }],
    },
    melody_merit: { available: false, missing: ["t_b"] },
    rhythm_merit: { available: false, missing: ["t_b"] },
    timbre_merit: { available: false, missing: ["t_b"] },
    lyrics_sonar: { available: false, missing: ["t_a", "t_b"] },
  },
};

describe("orientation", () => {
  it("keeps canonical order when A is the canonical first track", () => {
    const r = orient(entry, "overall_peav", "t_a");
    expect(r.rankBForA).toBe(2);
    expect(r.excerpts[0].a.track_id).toBe("t_a");
  });
  it("swaps sides and ranks when the user's A is canonical B", () => {
    const r = orient(entry, "overall_peav", "t_b");
    expect(r.rankBForA).toBe(5);
    expect(r.rankAForB).toBe(2);
    expect(r.excerpts[0].a).toEqual({ track_id: "t_b", start: 30, end: 40 });
  });
  it("reports unavailable relations without a score", () => {
    const r = orient(entry, "lyrics_sonar", "t_a");
    expect(r.available).toBe(false);
    expect(r.score).toBeUndefined();
  });
});

describe("helpers", () => {
  it("pairKey is order independent", () => {
    expect(pairKey("t_b", "t_a")).toBe("t_a|t_b");
  });
  it("formats real times", () => {
    expect(mmss(83.25)).toBe("01:23.3");
  });
  it("explains missing lyrics as a status, not zero, in both languages", () => {
    expect(reasonText(DICTS.en, "lyrics_not_provided")).toBe("No lyrics provided");
    expect(reasonText(DICTS.ja, "lyrics_not_provided")).toBe("歌詞未提供");
  });
  it("has the same keys in every language", () => {
    expect(Object.keys(DICTS.ja).sort()).toEqual(Object.keys(DICTS.en).sort());
  });
  it("indexes every evidence id", () => {
    const data = { tracks: [], pairs: { "t_a|t_b": entry } } as unknown as ExportData;
    const idx = buildEvidenceIndex(data);
    expect([...idx.keys()].sort()).toEqual(["con:overall_peav:t_a:t_b:t_a", "exc:overall_peav:t_a:t_b:0", "rel:overall_peav:t_a:t_b"]);
  });
});

describe("interpretation language", () => {
  const mk = (lang: string, created: string) =>
    ({ kind: "pair_explanation", subject: { pair: ["t_a", "t_b"] }, prompt: { output_language: lang }, created_at: created }) as unknown as import("./types").Interpretation;
  it("prefers the UI language and flags fallbacks", () => {
    const items = [mk("zh-Hans", "2026-11-04T01:00:00"), mk("en", "2026-11-04T02:00:00"), mk("ja", "2026-11-04T03:00:00")];
    expect(pickInterpretations(items, "en")).toEqual([{ item: items[1] }]);
    expect(pickInterpretations([items[0]], "ja")).toEqual([{ item: items[0], fallbackFrom: "zh-Hans" }]);
  });
});
