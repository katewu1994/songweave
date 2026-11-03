import type { EvidenceRef } from "../data";
import { useT, viewName, type Dict } from "../i18n";
import type { Claim, Interpretation, Track } from "../types";
import { EvidenceChip, type EvidenceActions } from "./Evidence";

interface Props {
  item: Interpretation;
  fallbackFrom?: string; // set when the card is shown in a language other than the UI language
  tracks: Record<string, Track>;
  index: Map<string, EvidenceRef>;
  actions: EvidenceActions;
}

function aspectLabel(t: Dict, a: string): string {
  return (t as unknown as Record<string, string>)[`aspect_${a}`] ?? a;
}

function Claims({ title, claims, label, tracks, index, actions }: { title: string; claims: Claim[]; label: (c: Claim) => string; tracks: Record<string, Track>; index: Map<string, EvidenceRef>; actions: EvidenceActions }) {
  if (!claims.length) return null;
  return (
    <>
      <h5>{title}</h5>
      <ul className="claims">
        {claims.map((c, i) => (
          <li key={i}>
            <span className="tag">{label(c)}</span> {c.statement}
            <span className="chips">
              {c.evidence_ids.map((e) => (
                <EvidenceChip key={e} id={e} index={index} tracks={tracks} actions={actions} />
              ))}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function InterpretationCard({ item, fallbackFrom, tracks, index, actions }: Props) {
  const t = useT();
  const o = item.output;
  const pair = item.subject.pair;
  const lang = item.prompt.output_language;
  const textLang = lang === "zh-Hans" ? "zh-Hans" : lang;
  return (
    <article className={`interp review-${item.review.status}`}>
      <header>
        <span className="interp-kind">
          <span className="ai-dot" /> {item.kind === "pair_explanation" ? t.pairExplanation : t.lyricUnderstanding}
        </span>
        <span className={`badge review-${item.review.status}`}>{(t as unknown as Record<string, string>)[`review_${item.review.status}`]}</span>
      </header>
      <div className="interp-meta mono">
        {item.model} · {new Date(item.created_at).toLocaleString()} · {t.cached}
        <br />
        {t.citations}: {item.validation.status === "pass" ? t.pass : t.fail} · {t.scopeAudio(item.sent_scope.audio)} · {t.scopeLyrics(item.sent_scope.lyrics_text)} · {t.scopeIds(item.sent_scope.titles_or_artist)}
      </div>
      {fallbackFrom && <p className="lang-note">{t.otherLanguage(t.langNames[fallbackFrom] ?? fallbackFrom)}</p>}
      {pair && <p className="interp-meta">{t.interpPair(tracks[pair[0]]?.title ?? pair[0], tracks[pair[1]]?.title ?? pair[1])}</p>}
      {item.subject.track_id && <p className="interp-meta">{t.interpTrack(tracks[item.subject.track_id]?.title ?? item.subject.track_id)}</p>}
      <div lang={textLang}>
        {o.summary && <p className="summary">{o.summary}</p>}
        {o.overview && <p className="summary">{o.overview}</p>}
        <Claims title={t.similarities} claims={o.similarities ?? []} label={(c) => viewName(t, c.dimension ?? "")} tracks={tracks} index={index} actions={actions} />
        <Claims title={t.differences} claims={o.differences ?? []} label={(c) => viewName(t, c.dimension ?? "")} tracks={tracks} index={index} actions={actions} />
        <Claims title={t.observations} claims={o.observations ?? []} label={(c) => aspectLabel(t, c.aspect ?? "")} tracks={tracks} index={index} actions={actions} />
        {!!o.listening_guide?.length && (
          <>
            <h5>{t.listenFor}</h5>
            <ul className="claims">
              {o.listening_guide.map((g, i) => (
                <li key={i}>
                  {g.suggestion} <EvidenceChip id={g.evidence_id} index={index} tracks={tracks} actions={actions} />
                </li>
              ))}
            </ul>
          </>
        )}
        {!!o.uncertainties.length && (
          <>
            <h5>{t.uncertainties}</h5>
            <ul className="uncertain">
              {o.uncertainties.map((u, i) => (
                <li key={i}>{u}</li>
              ))}
            </ul>
          </>
        )}
      </div>
      {!!item.validation.lint_flags.length && <p className="lint">⚠ {t.lintWarn(item.validation.lint_flags.length)}</p>}
      {item.review.note && (
        <p className="interp-meta">
          {t.reviewNote}: {item.review.note}
        </p>
      )}
    </article>
  );
}
