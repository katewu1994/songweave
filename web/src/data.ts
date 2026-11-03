import type { Contrast, Excerpt, ExportData, Interpretation, InterpretationsData, LyricPair, PairEntry, Relation, Segment, ViewId } from "./types";

export class LoadError extends Error {
  constructor(public status: number) {
    super(`HTTP ${status}`);
  }
}

export async function loadBundle(): Promise<{ data: ExportData; interp: InterpretationsData }> {
  const [d, i] = await Promise.all([fetch("/data/export.json"), fetch("/data/interpretations.json")]);
  if (!d.ok) throw new LoadError(d.status);
  const data = (await d.json()) as ExportData;
  const interp = i.ok ? ((await i.json()) as InterpretationsData) : { schema: "", items: [], failed_validation_count: 0 };
  return { data, interp };
}

export function pairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

export function mmss(t: number): string {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${String(m).padStart(2, "0")}:${r.toFixed(1).padStart(4, "0")}`;
}

/** A relation seen from the user's A→B orientation (the export stores canonical sorted pairs). */
export interface OrientedRelation {
  available: boolean;
  missing: string[];
  relationId?: string;
  score?: number;
  rankBForA?: number;
  rankAForB?: number;
  nCandidates?: number;
  pairRank?: number;
  nPairs?: number;
  excerpts: { id: string; score: number; a: Segment; b: Segment }[];
  contrasts: Contrast[];
  lyricPairs: { id: string; score: number; a: LyricPair["a"]; b: LyricPair["b"] }[];
}

export function orient(entry: PairEntry, view: ViewId, a: string): OrientedRelation {
  const rel: Relation = entry.views[view];
  const flipped = entry.a !== a;
  if (!rel.available) return { available: false, missing: rel.missing, excerpts: [], contrasts: [], lyricPairs: [] };
  const ex = (e: Excerpt) => (flipped ? { id: e.id, score: e.score, a: e.b, b: e.a } : { id: e.id, score: e.score, a: e.a, b: e.b });
  const lp = (e: LyricPair) => (flipped ? { id: e.id, score: e.score, a: e.b, b: e.a } : { id: e.id, score: e.score, a: e.a, b: e.b });
  return {
    available: true,
    missing: [],
    relationId: rel.relation_id,
    score: rel.score,
    rankBForA: flipped ? rel.rank_a_for_b : rel.rank_b_for_a,
    rankAForB: flipped ? rel.rank_b_for_a : rel.rank_a_for_b,
    nCandidates: rel.n_candidates,
    pairRank: rel.pair_rank,
    nPairs: rel.n_pairs,
    excerpts: (rel.excerpts ?? []).map(ex),
    contrasts: rel.contrasts ?? [],
    lyricPairs: (rel.lyric_pairs ?? []).map(lp),
  };
}

/** Index of every evidence item in the export, for resolving citations in interpretations. */
export type EvidenceRef =
  | { type: "relation"; view: ViewId; pair: PairEntry }
  | { type: "excerpt"; view: ViewId; excerpt: Excerpt }
  | { type: "contrast"; view: ViewId; contrast: Contrast }
  | { type: "lyric_block"; trackId: string; index: number; text: string }
  | { type: "lyric_pair"; pair: LyricPair };

export function buildEvidenceIndex(data: ExportData): Map<string, EvidenceRef> {
  const idx = new Map<string, EvidenceRef>();
  for (const t of data.tracks) for (const b of t.lyrics.blocks ?? []) idx.set(b.evidence_id, { type: "lyric_block", trackId: t.track_id, index: b.index, text: b.text });
  for (const p of Object.values(data.pairs)) {
    for (const [view, rel] of Object.entries(p.views) as [ViewId, Relation][]) {
      if (!rel.available) continue;
      idx.set(rel.relation_id, { type: "relation", view, pair: p });
      for (const e of rel.excerpts ?? []) idx.set(e.id, { type: "excerpt", view, excerpt: e });
      for (const c of rel.contrasts ?? []) idx.set(c.id, { type: "contrast", view, contrast: c });
      for (const l of rel.lyric_pairs ?? []) idx.set(l.id, { type: "lyric_pair", pair: l });
    }
  }
  return idx;
}

/**
 * One interpretation per (kind, subject): the newest in the UI language if it exists, otherwise the
 * newest in any language, flagged so the card can say it is not in the UI language.
 */
export function pickInterpretations(items: Interpretation[], lang: string): { item: Interpretation; fallbackFrom?: string }[] {
  const groups = new Map<string, Interpretation[]>();
  for (const it of items) {
    const subj = it.subject.track_id ?? [...(it.subject.pair ?? [])].sort().join("|");
    const k = `${it.kind}:${subj}`;
    groups.set(k, [...(groups.get(k) ?? []), it]);
  }
  const out: { item: Interpretation; fallbackFrom?: string }[] = [];
  for (const g of groups.values()) {
    const newest = (xs: Interpretation[]) => [...xs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    const same = g.filter((x) => x.prompt.output_language === lang);
    if (same.length) out.push({ item: newest(same) });
    else {
      const any = newest(g);
      out.push({ item: any, fallbackFrom: any.prompt.output_language });
    }
  }
  return out;
}
