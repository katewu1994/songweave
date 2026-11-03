import { useMemo, useState } from "react";
import { lyricsStatus, reasonText, useT, viewName } from "../i18n";
import { COLOR_A, COLOR_B, VIEW_COLOR } from "../theme";
import type { Neighbor, Track, ViewId } from "../types";
import { VIEW_IDS } from "../types";

export type Slot = "A" | "B";

interface Props {
  tracks: Track[];
  view: ViewId;
  selA: string | null;
  selB: string | null;
  active: Slot;
  /** Original-space ranking of every other song for A in the current view (if A is in it). */
  rankingForA: Neighbor[] | null;
  onPick: (id: string) => void;
  onActivate: (slot: Slot) => void;
  onClear: (slot: Slot) => void;
  onSwap: () => void;
}

function SlotBox({ slot, id, tracks, active, onActivate, onClear }: { slot: Slot; id: string | null; tracks: Record<string, Track>; active: boolean; onActivate: () => void; onClear: () => void }) {
  const t = useT();
  const color = slot === "A" ? COLOR_A : COLOR_B;
  return (
    <div className={`slot${active ? " active" : ""}${id ? " filled" : ""}`} style={{ ["--sc" as string]: color }}>
      <button className="slot-main" onClick={onActivate} aria-pressed={active} title={t.slotHint(slot)}>
        <b className="slot-tag">{slot}</b>
        <span className="slot-text">
          <small>{slot === "A" ? t.slotA : t.slotB}</small>
          <span className={id ? "" : "muted"}>{id ? tracks[id]?.title ?? id : t.slotEmpty}</span>
        </span>
      </button>
      {id && (
        <button className="slot-clear" onClick={onClear} aria-label={`${t.clearSlot} ${slot}`} title={t.clearSlot}>
          ✕
        </button>
      )}
    </div>
  );
}

export function TrackList({ tracks, view, selA, selB, active, rankingForA, onPick, onActivate, onClear, onSwap }: Props) {
  const t = useT();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"library" | "closest">("library");
  const byId = useMemo(() => Object.fromEntries(tracks.map((x) => [x.track_id, x])) as Record<string, Track>, [tracks]);
  const rankOf = useMemo(() => new Map((rankingForA ?? []).map((n) => [n.track_id, n])), [rankingForA]);
  const canSortClosest = !!selA && !!rankingForA;
  const sortMode = canSortClosest ? sort : "library";
  const range = rankingForA?.length ? [rankingForA[rankingForA.length - 1].score, rankingForA[0].score] : [0, 1];

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    let list = s ? tracks.filter((x) => `${x.title} ${x.artist ?? ""} ${x.track_id}`.toLowerCase().includes(s)) : tracks;
    if (sortMode === "closest") {
      list = [...list].sort((a, b) => (a.track_id === selA ? -1 : b.track_id === selA ? 1 : (rankOf.get(a.track_id)?.rank ?? 999) - (rankOf.get(b.track_id)?.rank ?? 999)));
    }
    return list;
  }, [q, tracks, sortMode, rankOf, selA]);

  return (
    <aside className="tracklist">
      <div className="search-wrap">
        <div className="slots">
          <SlotBox slot="A" id={selA} tracks={byId} active={active === "A"} onActivate={() => onActivate("A")} onClear={() => onClear("A")} />
          <button className="slot-swap" onClick={onSwap} disabled={!selA || !selB} title={t.swap} aria-label={t.swap}>
            ⇅
          </button>
          <SlotBox slot="B" id={selB} tracks={byId} active={active === "B"} onActivate={() => onActivate("B")} onClear={() => onClear("B")} />
        </div>
        <input className="search" placeholder={t.searchPlaceholder} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t.searchPlaceholder} />
        <div className="seg sort" role="group">
          <button className={sortMode === "library" ? "on" : ""} onClick={() => setSort("library")}>
            {t.sortLibrary}
          </button>
          <button className={sortMode === "closest" ? "on" : ""} disabled={!canSortClosest} onClick={() => setSort("closest")}>
            {t.sortClosest}
          </button>
        </div>
        {sortMode === "closest" && <p className="sort-hint">{t.closestHint(viewName(t, view))}</p>}
      </div>
      <ul className={`active-${active.toLowerCase()}`}>
        {shown.map((x) => {
          const inView = x.coverage[view] === "full";
          const isA = x.track_id === selA;
          const isB = x.track_id === selB;
          const n = rankOf.get(x.track_id);
          const blocked = active === "B" && isA;
          return (
            <li key={x.track_id} className={`${isA ? "sel-a" : isB ? "sel-b" : ""}${inView ? "" : " out"}`}>
              <button className="track-main" onClick={() => onPick(x.track_id)} disabled={blocked} title={blocked ? "" : t.slotHint(active)}>
                <span className="track-title">
                  {isA && <b className="tag-a">A</b>}
                  {isB && <b className="tag-b">B</b>}
                  <span className="tt">{x.title}</span>
                  {selA && !isA && n && (
                    <span className="rank-chip mono" title={`${viewName(t, view)} · ${n.score.toFixed(3)}`}>
                      #{n.rank}
                    </span>
                  )}
                </span>
                <span className="track-meta">
                  <span className="mono">
                    {Math.floor(x.duration_seconds / 60)}:{String(Math.round(x.duration_seconds % 60)).padStart(2, "0")}
                  </span>
                  {selA && !isA && n ? (
                    <span className="sim-bar" title={n.score.toFixed(3)}>
                      <i style={{ width: `${8 + 92 * ((n.score - range[0]) / Math.max(1e-9, range[1] - range[0]))}%`, background: VIEW_COLOR[view] }} />
                    </span>
                  ) : (
                    <span className="cov">
                      {VIEW_IDS.map((v) => (
                        <i key={v} style={x.coverage[v] === "full" ? { background: VIEW_COLOR[v] } : undefined} className={x.coverage[v] === "full" ? "ok" : "no"} title={`${viewName(t, v)}: ${reasonText(t, x.coverage[v])}`} />
                      ))}
                    </span>
                  )}
                  {x.lyrics.status !== "available" && <span className="lyr">{lyricsStatus(t, x.lyrics.status)}</span>}
                </span>
                {!blocked && !isA && !isB && (
                  <span className="pick-hint" aria-hidden>
                    → {active}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
