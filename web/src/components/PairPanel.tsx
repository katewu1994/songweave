import type { EvidenceRef } from "../data";
import { mmss, orient, pairKey, pickInterpretations, type OrientedRelation } from "../data";
import { lyricsStatus, useT, viewDesc, viewName, type Dict, type Lang } from "../i18n";
import { COLOR_A, COLOR_B, VIEW_COLOR } from "../theme";
import type { ExportData, Interpretation, Track, View, ViewId } from "../types";
import { VIEW_IDS } from "../types";
import { segLabel, type EvidenceActions } from "./Evidence";
import { Fingerprint, closeness, closerThanPct } from "./Fingerprint";
import { GenerateBox } from "./GenerateBox";
import { InterpretationCard } from "./InterpretationCard";

interface Props {
  data: ExportData;
  tracks: Record<string, Track>;
  views: Record<ViewId, View>;
  view: ViewId;
  selA: string;
  selB: string | null;
  interps: Interpretation[];
  lang: Lang;
  index: Map<string, EvidenceRef>;
  actions: EvidenceActions;
  onPickB: (id: string | null) => void;
  onSwap: () => void;
  canGenerate: boolean;
  onRefresh: () => Promise<void>;
}

function missingText(t: Dict, tracks: Record<string, Track>, view: ViewId, ids: string[]): string {
  return ids
    .map((id) => `${tracks[id]?.title ?? id}: ${view === "lyrics_sonar" ? lyricsStatus(t, tracks[id]?.lyrics.status ?? "") : t.analysisMissing}`)
    .join(" · ");
}

function Cards({ list, tracks, index, actions }: { list: { item: Interpretation; fallbackFrom?: string }[]; tracks: Record<string, Track>; index: Map<string, EvidenceRef>; actions: EvidenceActions }) {
  return (
    <>
      {list.map(({ item, fallbackFrom }) => (
        <InterpretationCard key={item.interpretation_id} item={item} fallbackFrom={fallbackFrom} tracks={tracks} index={index} actions={actions} />
      ))}
    </>
  );
}

export function PairPanel({ data, tracks, views, view, selA, selB, interps, lang, index, actions, onPickB, onSwap, canGenerate, onRefresh }: Props) {
  const t = useT();
  const A = tracks[selA];
  const accent = VIEW_COLOR[view];
  const picked = pickInterpretations(interps, lang);
  const lyricCards = picked.filter(({ item }) => item.kind === "lyric_understanding" && (item.subject.track_id === selA || item.subject.track_id === selB));

  if (!selB) {
    const full = views[view].ranking?.[selA] ?? [];
    const top = full.slice(0, 6);
    const sMax = full[0]?.score ?? 1;
    const sMin = full[full.length - 1]?.score ?? 0;
    return (
      <section className="panel" style={{ ["--accent" as string]: accent }}>
        <div className="pair-head">
          <span className="pill" style={{ background: COLOR_A }}>A</span>
          <h2>{A.title}</h2>
        </div>
        <h3>
          <span className="dot" style={{ background: accent }} /> {t.closestIn(viewName(t, view))}
        </h3>
        {views[view].included.includes(selA) ? (
          <ol className="nbr-list">
            {top.map((n) => (
              <li key={n.track_id}>
                <span className="rank mono">{String(n.rank).padStart(2, "0")}</span>
                <span className="nbr-title">{tracks[n.track_id]?.title}</span>
                <span className="meter" title={t.cosineHelp}>
                  <i style={{ width: `${8 + 92 * ((n.score - sMin) / Math.max(1e-9, sMax - sMin))}%` }} />
                </span>
                <span className="mono small">{n.score.toFixed(3)}</span>
                <button className="ghost" onClick={() => onPickB(n.track_id)}>
                  {t.compare}
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="warn">
            {t.aNotInView} {missingText(t, tracks, view, [selA])}. {t.missingNotZero}
          </p>
        )}
        <h3>{t.nearestPerDim}</h3>
        <div className="dim-grid">
          {VIEW_IDS.map((v) => {
            const top1 = views[v].neighbors?.[selA]?.[0];
            return (
              <button key={v} className={`dim-card${v === view ? " on" : ""}`} style={{ ["--c" as string]: VIEW_COLOR[v] }} onClick={() => (top1 ? onPickB(top1.track_id) : actions.setView(v))}>
                <span className="dim-name">{viewName(t, v)}</span>
                <span className="dim-song">{top1 ? tracks[top1.track_id]?.title : t.unavailable}</span>
                <span className="mono small">{top1 ? top1.score.toFixed(3) : "—"}</span>
              </button>
            );
          })}
        </div>
        <Cards list={lyricCards} tracks={tracks} index={index} actions={actions} />
      </section>
    );
  }

  const B = tracks[selB];
  const entry = data.pairs[pairKey(selA, selB)];
  const rels = Object.fromEntries(VIEW_IDS.map((v) => [v, orient(entry, v, selA)])) as Record<ViewId, OrientedRelation>;
  const cur = rels[view];
  const pairCards = picked.filter(({ item }) => item.kind === "pair_explanation" && item.subject.pair && pairKey(item.subject.pair[0], item.subject.pair[1]) === pairKey(selA, selB));

  return (
    <section className="panel" style={{ ["--accent" as string]: accent }}>
      <div className="pair-head">
        <span className="pill" style={{ background: COLOR_A }}>A</span>
        <h2>{A.title}</h2>
        <button className="icon" onClick={onSwap} title={t.swap} aria-label={t.swap}>
          ⇄
        </button>
        <span className="pill" style={{ background: COLOR_B }}>B</span>
        <h2>{B.title}</h2>
        <button className="icon close" onClick={() => onPickB(null)} title={t.clearB} aria-label={t.clearB}>
          ✕
        </button>
      </div>

      <div className="fp-block">
        <Fingerprint rels={rels} current={view} onPick={actions.setView} />
        <div className="fp-side">
          <h3>{t.fingerprint}</h3>
          <p className="muted small">{t.fingerprintHelp}</p>
          <ul className="fp-rows">
            {VIEW_IDS.map((v) => {
              const r = rels[v];
              const k = closeness(r);
              const pct = closerThanPct(r);
              return (
                <li
                  key={v}
                  className={v === view ? "on" : ""}
                  onClick={() => actions.setView(v)}
                  style={{ ["--c" as string]: VIEW_COLOR[v] }}
                  title={`${viewName(t, v)} · ${viewDesc(t, v)}${pct !== null ? ` · ${t.closerThan(pct)}` : ` · ${t.unavailable} ${t.notCountedZero}`}`}
                >
                  <span className="dim-name">{viewName(t, v)}</span>
                  {r.available ? (
                    <span className="gauge" role="img" aria-label={pct !== null ? t.closerThan(pct) : ""}>
                      <i className="fill" style={{ width: `${Math.max(3, 100 * (k ?? 0))}%` }} />
                    </span>
                  ) : (
                    <span className="gauge na" role="img" aria-label={t.unavailable} />
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      <table className="dims">
        <thead>
          <tr>
            <th>{t.dim}</th>
            <th title={t.cosineHelp}>{t.cosine} ⓘ</th>
            <th>{t.rankBinA}</th>
            <th>{t.pairRank}</th>
          </tr>
        </thead>
        <tbody>
          {VIEW_IDS.map((v) => {
            const r = rels[v];
            return (
              <tr key={v} className={v === view ? "current" : ""} onClick={() => actions.setView(v)} style={{ ["--c" as string]: VIEW_COLOR[v] }}>
                <th>
                  <span className="dim-name">{viewName(t, v)}</span>
                  <div className="model">{views[v].model_label}</div>
                </th>
                {r.available ? (
                  <>
                    <td className="mono">{r.score!.toFixed(3)}</td>
                    <td className="mono">
                      {r.rankBForA}/{r.nCandidates}
                    </td>
                    <td className="mono" title={`${r.pairRank}/${r.nPairs}`}>
                      {closerThanPct(r)}%
                    </td>
                  </>
                ) : (
                  <td colSpan={3} className="muted small">
                    {missingText(t, tracks, v, r.missing)} {t.notCountedZero}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>
        <span className="dot" style={{ background: accent }} /> {t.evidence(viewName(t, view))}
      </h3>
      {!cur.available && (
        <p className="warn">
          {t.unavailableBecause}: {missingText(t, tracks, view, cur.missing)}
        </p>
      )}
      {cur.excerpts.length > 0 && (
        <ul className="evidence">
          {cur.excerpts.map((e, i) => {
            const a = { segment: e.a, label: segLabel(tracks, e.a.track_id, e.a.start, e.a.end) };
            const b = { segment: e.b, label: segLabel(tracks, e.b.track_id, e.b.start, e.b.end) };
            return (
              <li key={e.id}>
                <div className="ev-head">
                  <span>{t.similarExcerpt(i + 1)}</span>
                  <span className="mono small muted">
                    {t.windowScore} {e.score.toFixed(3)}
                  </span>
                </div>
                <div className="ev-actions">
                  <button className="play a" onClick={() => actions.play({ ...a, alternate: b })}>
                    ▶ A <span className="mono">{mmss(e.a.start)}–{mmss(e.a.end)}</span>
                  </button>
                  <button className="play b" onClick={() => actions.play({ ...b, alternate: a })}>
                    ▶ B <span className="mono">{mmss(e.b.start)}–{mmss(e.b.end)}</span>
                  </button>
                </div>
              </li>
            );
          })}
          {cur.contrasts.map((c) => {
            const s = c.segment;
            const side = s.track_id === selA ? "A" : "B";
            return (
              <li key={c.id} className="contrast">
                <div className="ev-head">
                  <span>{t.contrastExcerpt(side)}</span>
                  <span className="mono small muted">
                    {t.bestMatch} {c.best_match_score.toFixed(3)}
                  </span>
                </div>
                <div className="ev-actions">
                  <button className={`play ${side.toLowerCase()}`} onClick={() => actions.play({ segment: s, label: segLabel(tracks, s.track_id, s.start, s.end) })}>
                    ▶ {side} <span className="mono">{mmss(s.start)}–{mmss(s.end)}</span>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {cur.lyricPairs.length > 0 && (
        <ul className="evidence">
          {cur.lyricPairs.map((lp) => {
            const ta = index.get(lp.a.evidence_id);
            const tb = index.get(lp.b.evidence_id);
            return (
              <li key={lp.id} className="lyric-pair">
                <div className="ev-head">
                  <span className="mono small muted">
                    {t.lyricBlockScore} {lp.score.toFixed(3)}
                  </span>
                </div>
                <blockquote lang="ja" className="a">{ta?.type === "lyric_block" ? ta.text : lp.a.evidence_id}</blockquote>
                <blockquote lang="ja" className="b">{tb?.type === "lyric_block" ? tb.text : lp.b.evidence_id}</blockquote>
              </li>
            );
          })}
        </ul>
      )}
      <p className="muted small">{t.excerptNote}</p>

      <h3>
        <span className="ai-dot" /> {t.metaInsights}
      </h3>
      {pairCards.length === 0 ? (
        <>
          <p className="muted small">{t.noInterpretation}</p>
          {canGenerate && <GenerateBox key={`${entry.a}|${entry.b}|${lang}`} a={entry.a} b={entry.b} lang={lang} fallback={false} onDone={onRefresh} />}
        </>
      ) : (
        <>
          {canGenerate && pairCards.some((c) => c.fallbackFrom) && <GenerateBox key={`${entry.a}|${entry.b}|${lang}`} a={entry.a} b={entry.b} lang={lang} fallback onDone={onRefresh} />}
          <Cards list={pairCards} tracks={tracks} index={index} actions={actions} />
        </>
      )}
      <Cards list={lyricCards} tracks={tracks} index={index} actions={actions} />
    </section>
  );
}
