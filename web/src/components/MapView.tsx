import { useMemo, useRef, useState } from "react";
import type { Track, View } from "../types";
import { reasonText, useT, viewName } from "../i18n";
import { COLOR_A, COLOR_B, VIEW_COLOR, fade } from "../theme";

export type MapMode = "focus" | "overview";

interface Props {
  view: View;
  tracks: Record<string, Track>;
  selA: string | null;
  selB: string | null;
  mode: MapMode;
  onMode: (m: MapMode) => void;
  onPick: (id: string) => void; // fills the active A/B slot
  onPickA: (id: string) => void;
}

const SIZE = 1000;
const C = SIZE / 2;
const R_MIN = 110;
const R_MAX = 430;
const TOP = 3;

interface Placed {
  x: number;
  y: number;
  closeness: number; // 1 = closest to the focus song, 0 = farthest (within that song's ranking)
  rank?: number;
  score?: number;
}

/** Focus layout: radius from original-space similarity to A; direction borrowed from the overview layout. */
function focusLayout(view: View, a: string): { pts: Record<string, Placed>; range: [number, number] } | null {
  const full = view.ranking?.[a];
  const coords = view.coords;
  if (!full?.length || !coords?.[a]) return null;
  const sMax = full[0].score;
  const sMin = full[full.length - 1].score;
  const span = Math.max(1e-9, sMax - sMin);
  const [ax, ay] = coords[a];
  const items = full.map((n) => {
    const [x, y] = coords[n.track_id] ?? [ax, ay];
    const ang = x === ax && y === ay ? 0 : Math.atan2(-(y - ay), x - ax);
    const closeness = (n.score - sMin) / span;
    return { id: n.track_id, ang, r: R_MIN + (1 - closeness) * (R_MAX - R_MIN), closeness, rank: n.rank, score: n.score };
  });
  // Spread angles so nodes at similar radius do not overlap; the radius (measured similarity) never moves.
  for (let it = 0; it < 150; it++) {
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const p = items[i];
        const q = items[j];
        const d = Math.hypot(p.r * Math.cos(p.ang) - q.r * Math.cos(q.ang), p.r * Math.sin(p.ang) - q.r * Math.sin(q.ang));
        if (d < 62) {
          let diff = p.ang - q.ang;
          while (diff > Math.PI) diff -= 2 * Math.PI;
          while (diff < -Math.PI) diff += 2 * Math.PI;
          const push = diff >= 0 ? 0.012 : -0.012;
          p.ang += push;
          q.ang -= push;
        }
      }
    }
  }
  const pts: Record<string, Placed> = { [a]: { x: C, y: C, closeness: 1 } };
  for (const it of items) pts[it.id] = { x: C + it.r * Math.cos(it.ang), y: C + it.r * Math.sin(it.ang), closeness: it.closeness, rank: it.rank, score: it.score };
  return { pts, range: [sMin, sMax] };
}

function overviewLayout(view: View): Record<string, Placed> {
  const pts: Record<string, Placed> = {};
  for (const [id, [x, y]] of Object.entries(view.coords ?? {})) {
    pts[id] = { x: 90 + ((x + 1) / 2) * (SIZE - 180), y: 90 + (1 - (y + 1) / 2) * (SIZE - 180), closeness: 0.6 };
  }
  return pts;
}

export function MapView({ view, tracks, selA, selB, mode, onMode, onPick, onPickA }: Props) {
  const t = useT();
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hover, setHover] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const accent = VIEW_COLOR[view.view_id];
  const dim = viewName(t, view.view_id);

  const aInView = !!selA && view.included.includes(selA);
  const focus = useMemo(() => (mode === "focus" && aInView && selA ? focusLayout(view, selA) : null), [mode, aInView, selA, view]);
  const pts = useMemo(() => focus?.pts ?? overviewLayout(view), [focus, view]);
  const effective: MapMode = focus ? "focus" : "overview";
  const nbrs = useMemo(() => (selA && view.neighbors?.[selA] ? view.neighbors[selA].slice(0, TOP) : []), [selA, view]);

  // Label collision avoidance; A, B, top neighbours and the hovered node always keep their labels.
  const labelled = useMemo(() => {
    const priority = [selA, selB, hover, ...nbrs.map((n) => n.track_id)].filter((x): x is string => !!x && !!pts[x]);
    const order = [...new Set([...priority, ...Object.keys(pts)])];
    const placed: { x: number; y: number; w: number }[] = [];
    const keep = new Set<string>();
    const fs = 19 / zoom;
    for (const id of order) {
      const p = pts[id];
      const w = (tracks[id]?.title.length ?? 4) * fs;
      const left = p.x * zoom + pan.x > SIZE * 0.7;
      const x = left ? p.x - 18 / zoom - w : p.x + 18 / zoom;
      const clash = placed.some((q) => Math.abs(q.y - p.y) < fs * 1.15 && x < q.x + q.w && q.x < x + w);
      if (!clash || priority.includes(id)) {
        keep.add(id);
        placed.push({ x, y: p.y, w });
      }
    }
    return keep;
  }, [pts, selA, selB, hover, nbrs, zoom, pan, tracks]);

  const toSvg = (cx: number, cy: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: ((cx - r.left) / r.width) * SIZE, y: ((cy - r.top) / r.height) * SIZE };
  };
  const onWheel = (e: React.WheelEvent) => {
    const p = toSvg(e.clientX, e.clientY);
    const nz = Math.min(6, Math.max(0.6, zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    setPan({ x: p.x - ((p.x - pan.x) * nz) / zoom, y: p.y - ((p.y - pan.y) * nz) / zoom });
    setZoom(nz);
  };
  const onDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y, moved: false };
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const r = svgRef.current!.getBoundingClientRect();
    const dx = ((e.clientX - d.x) / r.width) * SIZE;
    const dy = ((e.clientY - d.y) / r.height) * SIZE;
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
    if (d.moved) setPan({ x: d.px + dx, y: d.py + dy });
  };
  const onUp = () => {
    drag.current = null;
  };
  const nodeClick = (id: string) => (e: React.MouseEvent) => {
    e.stopPropagation();
    if (drag.current?.moved) return;
    if (id !== selA) onPick(id);
  };

  if (view.status === "unavailable") {
    return (
      <div className="map-card map-empty">
        <p>
          <strong>{dim}</strong> — {t.unavailable}
        </p>
        <ExcludedList view={view} tracks={tracks} />
      </div>
    );
  }

  const ev = view.explained_variance_2d;
  const aTitle = selA ? tracks[selA]?.title ?? selA : "";
  const headline = effective === "focus" ? t.focusExplain(aTitle, dim) : selA && !aInView ? `${aTitle} — ${t.notInView}` : selA ? t.overviewExplain : t.pickPrompt;

  return (
    <div className="map-card" style={{ ["--accent" as string]: accent }}>
      <div className="map-top">
        <div className="map-explain">
          <strong>{headline}</strong>
          <span>{effective === "focus" ? t.focusHowTo : `${t.overviewExplain} ${t.overviewHowTo}`}</span>
        </div>
        <div className="seg" role="tablist" aria-label="map mode">
          <button role="tab" aria-selected={effective === "focus"} className={effective === "focus" ? "on" : ""} disabled={!aInView} onClick={() => onMode("focus")}>
            {t.modeFocus}
          </button>
          <button role="tab" aria-selected={effective === "overview"} className={effective === "overview" ? "on" : ""} onClick={() => onMode("overview")}>
            {t.modeOverview}
          </button>
        </div>
      </div>
      <svg ref={svgRef} className="map" viewBox={`0 0 ${SIZE} ${SIZE}`} onWheel={onWheel} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp} role="img" aria-label={`${dim} map`}>
        <defs>
          <radialGradient id="core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={accent} stopOpacity="0.20" />
            <stop offset="70%" stopColor={accent} stopOpacity="0.04" />
            <stop offset="100%" stopColor={accent} stopOpacity="0" />
          </radialGradient>
          <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
          {effective === "focus" ? (
            <g>
              <circle cx={C} cy={C} r={R_MAX + 40} fill="url(#core)" />
              {[0, 1 / 3, 2 / 3, 1].map((k) => (
                <circle key={k} cx={C} cy={C} r={R_MIN + k * (R_MAX - R_MIN)} className="ring" strokeWidth={1.2 / zoom} />
              ))}
              <text x={C} y={C - R_MIN + 22 / zoom} className="ring-label" fontSize={14 / zoom} textAnchor="middle">
                ▲ {t.ringClosest}
              </text>
              <text x={C} y={C - R_MAX - 10 / zoom} className="ring-label" fontSize={14 / zoom} textAnchor="middle">
                {t.ringFarthest}
              </text>
            </g>
          ) : (
            <g className="grid">
              {Array.from({ length: 9 }, (_, i) => 100 + i * 100).map((v) => (
                <g key={v}>
                  <line x1={v} y1={40} x2={v} y2={960} strokeWidth={1 / zoom} />
                  <line x1={40} y1={v} x2={960} y2={v} strokeWidth={1 / zoom} />
                </g>
              ))}
            </g>
          )}
          {selA &&
            pts[selA] &&
            nbrs.map((n) =>
              pts[n.track_id] ? <line key={n.track_id} className="nbr-line" x1={pts[selA].x} y1={pts[selA].y} x2={pts[n.track_id].x} y2={pts[n.track_id].y} stroke={accent} strokeWidth={2.6 / zoom} /> : null,
            )}
          {selA && selB && pts[selA] && pts[selB] && <line className="pair-line" x1={pts[selA].x} y1={pts[selA].y} x2={pts[selB].x} y2={pts[selB].y} stroke={COLOR_B} strokeWidth={2.6 / zoom} />}
          {Object.entries(pts).map(([id, p]) => {
            const isA = id === selA;
            const isB = id === selB;
            const nb = nbrs.find((n) => n.track_id === id);
            const hot = isA || isB || !!nb;
            const fill = isA ? COLOR_A : isB ? COLOR_B : effective === "focus" ? fade(accent, 0.12 + 0.88 * p.closeness) : fade(accent, nb ? 1 : 0.55);
            const r = (isA ? 18 : hot ? 12 : 9) / Math.sqrt(zoom);
            const left = p.x * zoom + pan.x > SIZE * 0.7;
            return (
              <g key={id} className={`node${hot ? " hot" : ""}`} onClick={nodeClick(id)} onDoubleClick={() => onPickA(id)} onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)} data-track={id}>
                <title>
                  {tracks[id]?.title ?? id}
                  {p.score !== undefined ? ` · #${p.rank} · ${p.score.toFixed(3)}` : ""}
                </title>
                {hot && <circle cx={p.x} cy={p.y} r={r * 2} fill={fill} opacity={0.16} className={isA ? "pulse" : undefined} />}
                <circle cx={p.x} cy={p.y} r={r} fill={fill} filter={hot ? "url(#glow)" : undefined} />
                {nb && !isB && (
                  <text x={p.x} y={p.y + 4.5 / zoom} className="rank-badge" fontSize={13 / zoom} textAnchor="middle">
                    {nb.rank}
                  </text>
                )}
                {labelled.has(id) && (
                  <text x={left ? p.x - 18 / zoom : p.x + 18 / zoom} textAnchor={left ? "end" : "start"} y={p.y + 6 / zoom} fontSize={(isA ? 22 : 18) / zoom} className={hot || hover === id ? "lbl strong" : "lbl"}>
                    {tracks[id]?.title ?? id}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="map-foot">
        {effective === "focus" && focus ? (
          <div className="legend">
            <span className="muted">{t.ringClosest}</span>
            <span className="mono">{focus.range[1].toFixed(3)}</span>
            <span className="legend-bar" style={{ background: `linear-gradient(90deg, ${fade(accent, 1)}, ${fade(accent, 0.12)})` }} />
            <span className="mono">{focus.range[0].toFixed(3)}</span>
            <span className="muted">{t.ringFarthest}</span>
          </div>
        ) : (
          <span className="muted">{ev ? t.keptVariance(Math.round(100 * (ev[0] + ev[1]))) : ""}</span>
        )}
        <span className="hint">{t.mapHint}</span>
        <button
          className="ghost"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          {t.resetView}
        </button>
      </div>
      <ExcludedList view={view} tracks={tracks} />
    </div>
  );
}

function ExcludedList({ view, tracks }: { view: View; tracks: Record<string, Track> }) {
  const t = useT();
  if (!view.excluded.length) return null;
  return (
    <details className="excluded">
      <summary>{t.absentFromView(view.excluded.length)}</summary>
      <ul>
        {view.excluded.map((e) => (
          <li key={e.track_id}>
            {tracks[e.track_id]?.title ?? e.track_id} — {reasonText(t, e.reason)}
          </li>
        ))}
      </ul>
    </details>
  );
}
