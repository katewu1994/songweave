// Mirrors docs/DATA_CONTRACTS.md (export schema songweave.export.v1.2).

export type ViewId = "overall_peav" | "melody_merit" | "rhythm_merit" | "timbre_merit" | "lyrics_sonar";
export const VIEW_IDS: ViewId[] = ["overall_peav", "melody_merit", "rhythm_merit", "timbre_merit", "lyrics_sonar"];

export interface Neighbor {
  track_id: string;
  score: number;
  rank: number;
}

export interface View {
  view_id: ViewId;
  label_zh: string;
  space: string;
  model_label: string;
  provenance: { model_info?: Record<string, unknown>; settings?: Record<string, unknown> };
  included: string[];
  excluded: { track_id: string; reason: string }[];
  status: "ready" | "insufficient" | "unavailable";
  coords?: Record<string, [number, number]>;
  explained_variance_2d?: [number, number];
  neighbors?: Record<string, Neighbor[]>;
  ranking?: Record<string, Neighbor[]>;
  pair_score_stats?: { min: number; median: number; max: number; n_pairs: number };
}

export interface LyricBlock {
  index: number;
  text: string;
  line_start: number;
  line_end: number;
  evidence_id: string;
}

export interface Track {
  track_id: string;
  title: string;
  artist: string | null;
  duration_seconds: number;
  media: string;
  lyrics: { status: string; lang: string | null; blocks?: LyricBlock[] };
  coverage: Record<ViewId, string>;
}

export interface Segment {
  track_id: string;
  start: number;
  end: number;
}

export interface Excerpt {
  id: string;
  kind: "similar_excerpt";
  score: number;
  a: Segment;
  b: Segment;
}

export interface Contrast {
  id: string;
  kind: "contrast_excerpt";
  best_match_score: number;
  segment: Segment;
}

export interface LyricPair {
  id: string;
  kind: "similar_lyrics";
  score: number;
  a: { track_id: string; block: number; evidence_id: string };
  b: { track_id: string; block: number; evidence_id: string };
}

export type Relation =
  | { available: false; missing: string[] }
  | {
      available: true;
      relation_id: string;
      score: number;
      rank_b_for_a: number;
      rank_a_for_b: number;
      n_candidates: number;
      pair_rank: number;
      n_pairs: number;
      excerpts?: Excerpt[];
      contrasts?: Contrast[];
      lyric_pairs?: LyricPair[];
    };

export interface PairEntry {
  a: string;
  b: string;
  views: Record<ViewId, Relation>;
}

export interface ExportData {
  schema: string;
  generated_at: string;
  dataset: { id: string; name: string; kind: "real" | "fixture"; track_count: number };
  notices: string[];
  views: View[];
  tracks: Track[];
  pairs: Record<string, PairEntry>;
}

export interface Claim {
  dimension?: string;
  aspect?: string;
  statement: string;
  evidence_ids: string[];
}

export interface Interpretation {
  interpretation_id: string;
  kind: "pair_explanation" | "lyric_understanding";
  subject: { pair?: [string, string]; track_id?: string };
  model: string;
  created_at: string;
  prompt: { name: string; version: string; output_language: string };
  sent_scope: { audio: boolean; lyrics_text: boolean; titles_or_artist: boolean; dimensions: string[] };
  output: {
    summary?: string;
    similarities?: Claim[];
    differences?: Claim[];
    listening_guide?: { evidence_id: string; suggestion: string }[];
    overview?: string;
    observations?: Claim[];
    uncertainties: string[];
  };
  validation: { status: "pass" | "fail"; errors: string[]; lint_flags: { where: string; flag: string; detail: string }[] };
  review: { status: "unreviewed" | "approved" | "rejected"; reviewer: string | null; note: string | null; reviewed_at: string | null };
  generation: string;
}

export interface InterpretationsData {
  schema: string;
  items: Interpretation[];
  failed_validation_count: number;
}
