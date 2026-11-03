import type { EvidenceRef } from "../data";
import { mmss } from "../data";
import { useT, viewName } from "../i18n";
import type { PlayRequest } from "../player";
import { VIEW_COLOR } from "../theme";
import type { Track, ViewId } from "../types";

export interface EvidenceActions {
  play: (req: PlayRequest) => void;
  setView: (v: ViewId) => void;
}

export function segLabel(tracks: Record<string, Track>, trackId: string, start: number, end: number): string {
  return `${tracks[trackId]?.title ?? trackId} ${mmss(start)}–${mmss(end)}`;
}

/** A citation chip: shows what an evidence ID points to and acts on it (play / switch view). */
export function EvidenceChip({ id, index, tracks, actions }: { id: string; index: Map<string, EvidenceRef>; tracks: Record<string, Track>; actions: EvidenceActions }) {
  const t = useT();
  const ref = index.get(id);
  if (!ref) {
    return (
      <span className="chip chip-missing" title={t.chipMissing}>
        {id}
      </span>
    );
  }
  switch (ref.type) {
    case "excerpt": {
      const e = ref.excerpt;
      const a = { segment: e.a, label: segLabel(tracks, e.a.track_id, e.a.start, e.a.end) };
      const b = { segment: e.b, label: segLabel(tracks, e.b.track_id, e.b.start, e.b.end) };
      return (
        <button className="chip chip-play" style={{ ["--c" as string]: VIEW_COLOR[ref.view] }} onClick={() => actions.play({ ...a, alternate: b })} title={`${viewName(t, ref.view)} · ${t.windowScore} ${e.score.toFixed(3)}`}>
          ▶ {mmss(e.a.start)} ↔ {mmss(e.b.start)}
        </button>
      );
    }
    case "contrast": {
      const s = ref.contrast.segment;
      return (
        <button className="chip chip-play" style={{ ["--c" as string]: VIEW_COLOR[ref.view] }} onClick={() => actions.play({ segment: s, label: segLabel(tracks, s.track_id, s.start, s.end) })} title={t.chipContrastTitle}>
          ▶ {tracks[s.track_id]?.title ?? s.track_id} {mmss(s.start)}
        </button>
      );
    }
    case "relation":
      return (
        <button className="chip" style={{ ["--c" as string]: VIEW_COLOR[ref.view] }} onClick={() => actions.setView(ref.view)}>
          {t.chipRelation(viewName(t, ref.view))}
        </button>
      );
    case "lyric_block":
      return (
        <span className="chip chip-lyric" title={ref.text} lang="ja">
          {t.chipLyric(tracks[ref.trackId]?.title ?? ref.trackId, ref.index + 1)}
        </span>
      );
    case "lyric_pair":
      return (
        <span className="chip chip-lyric" title={`${ref.pair.score.toFixed(3)}`}>
          {t.chipLyricPair(ref.pair.a.block + 1, ref.pair.b.block + 1)}
        </span>
      );
  }
}
