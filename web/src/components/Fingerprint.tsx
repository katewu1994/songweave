import type { OrientedRelation } from "../data";
import { useT, viewName } from "../i18n";
import { VIEW_COLOR } from "../theme";
import type { ViewId } from "../types";
import { VIEW_IDS } from "../types";

/** Closeness of a pair within one dimension: 1 = most similar pair in the library, 0 = least. */
export function closeness(r: OrientedRelation): number | null {
  if (!r.available || !r.pairRank || !r.nPairs) return null;
  return r.nPairs > 1 ? 1 - (r.pairRank - 1) / (r.nPairs - 1) : 1;
}

/** Share of all other pairs in the library that this pair is closer than (0–100; higher = more similar). */
export function closerThanPct(r: OrientedRelation): number | null {
  if (!r.available || !r.pairRank || !r.nPairs) return null;
  return r.nPairs > 1 ? Math.round((100 * (r.nPairs - r.pairRank)) / (r.nPairs - 1)) : 100;
}

/** Five-axis radar of within-dimension pair ranks. Missing dimensions are drawn as gaps, not zeros. */
export function Fingerprint({ rels, current, onPick }: { rels: Record<ViewId, OrientedRelation>; current: ViewId; onPick: (v: ViewId) => void }) {
  const t = useT();
  const S = 280;
  const c = S / 2;
  const R = 96;
  const axis = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / VIEW_IDS.length;
  const pt = (i: number, k: number) => [c + Math.cos(axis(i)) * R * k, c + Math.sin(axis(i)) * R * k];
  const vals = VIEW_IDS.map((v) => closeness(rels[v]));
  const poly = vals.map((k, i) => (k === null ? null : pt(i, 0.08 + 0.92 * k)));
  const shown = poly.filter((p): p is number[] => p !== null);
  return (
    <svg className="fingerprint" viewBox={`0 0 ${S} ${S}`} role="img" aria-label={t.fingerprint}>
      {[0.25, 0.5, 0.75, 1].map((k) => (
        <polygon key={k} className="fp-web" points={VIEW_IDS.map((_, i) => pt(i, k).join(",")).join(" ")} />
      ))}
      {VIEW_IDS.map((v, i) => {
        const [x, y] = pt(i, 1);
        return <line key={v} className={vals[i] === null ? "fp-axis missing" : "fp-axis"} x1={c} y1={c} x2={x} y2={y} />;
      })}
      {shown.length >= 3 && <polygon className="fp-shape" points={shown.map((p) => p.join(",")).join(" ")} />}
      {poly.map((p, i) =>
        p ? <circle key={VIEW_IDS[i]} cx={p[0]} cy={p[1]} r={VIEW_IDS[i] === current ? 6 : 4.5} fill={VIEW_COLOR[VIEW_IDS[i]]} className="fp-dot" /> : null,
      )}
      {VIEW_IDS.map((v, i) => {
        const [x, y] = pt(i, 1.22);
        return (
          <text key={v} x={x} y={y + 4} textAnchor="middle" fill={VIEW_COLOR[v]} className={`fp-label${v === current ? " on" : ""}`} onClick={() => onPick(v)}>
            {viewName(t, v)}
          </text>
        );
      })}
    </svg>
  );
}
