import { useCallback, useEffect, useMemo, useState } from "react";
import { LoadError, buildEvidenceIndex, loadBundle } from "./data";
import { DICTS, LANGS, LangContext, initialLang, saveLang, viewDesc, viewName, type Lang } from "./i18n";
import { SegmentPlayer, type PlayRequest } from "./player";
import { VIEW_COLOR } from "./theme";
import type { ExportData, InterpretationsData, Track, View, ViewId } from "./types";
import { VIEW_IDS } from "./types";
import { MapView, type MapMode } from "./components/MapView";
import { PairPanel } from "./components/PairPanel";
import { PlayerBar } from "./components/PlayerBar";
import { TrackList, type Slot } from "./components/TrackList";

function readHash(): { a: string | null; b: string | null; view: ViewId } {
  const p = new URLSearchParams(window.location.hash.slice(1));
  const v = p.get("view") as ViewId | null;
  return { a: p.get("a"), b: p.get("b"), view: v && VIEW_IDS.includes(v) ? v : "overall_peav" };
}

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 40 40" aria-hidden>
      <path d="M4 14 C 14 4, 26 24, 36 14" />
      <path d="M4 20 C 14 30, 26 10, 36 20" />
      <path d="M4 26 C 14 16, 26 36, 36 26" />
    </svg>
  );
}

export function App() {
  const [bundle, setBundle] = useState<{ data: ExportData; interp: InterpretationsData } | null>(null);
  const [error, setError] = useState<number | null>(null);
  const [lang, setLang] = useState<Lang>(initialLang);
  const init = readHash();
  const [view, setView] = useState<ViewId>(init.view);
  const [selA, setSelA] = useState<string | null>(init.a);
  const [selB, setSelB] = useState<string | null>(init.b);
  const [mode, setMode] = useState<MapMode>("focus");
  const [canGenerate, setCanGenerate] = useState(false);
  const t = DICTS[lang];

  useEffect(() => {
    loadBundle().then(setBundle, (e: unknown) => setError(e instanceof LoadError ? e.status : 0));
    fetch("/api/status")
      .then((r) => (r.ok ? r.json() : { available: false }))
      .then((s: { available?: boolean }) => setCanGenerate(!!s.available))
      .catch(() => setCanGenerate(false));
    const onHash = () => {
      const h = readHash();
      setView(h.view);
      setSelA(h.a);
      setSelB(h.b);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const p = new URLSearchParams();
    p.set("view", view);
    if (selA) p.set("a", selA);
    if (selB) p.set("b", selB);
    window.history.replaceState(null, "", `#${p.toString()}`);
  }, [view, selA, selB]);

  useEffect(() => {
    document.documentElement.lang = lang;
    saveLang(lang);
  }, [lang]);

  const tracks = useMemo(() => Object.fromEntries((bundle?.data.tracks ?? []).map((x) => [x.track_id, x])) as Record<string, Track>, [bundle]);
  const views = useMemo(() => Object.fromEntries((bundle?.data.views ?? []).map((v) => [v.view_id, v])) as Record<ViewId, View>, [bundle]);
  const index = useMemo(() => (bundle ? buildEvidenceIndex(bundle.data) : new Map()), [bundle]);
  const player = useMemo(() => new SegmentPlayer((id) => `/data/${tracks[id]?.media ?? ""}`), [tracks]);
  useEffect(() => () => player.stop(), [player]);

  const refreshInterp = useCallback(async () => {
    const r = await fetch(`/data/interpretations.json?t=${Date.now()}`);
    if (!r.ok) return;
    const interp = (await r.json()) as InterpretationsData;
    setBundle((b) => (b ? { ...b, interp } : b));
  }, []);
  const play = useCallback((req: PlayRequest) => void player.play(req).catch(() => undefined), [player]);
  const [active, setActive] = useState<Slot>(init.a ? "B" : "A");
  const pickA = useCallback((id: string) => {
    setSelA(id);
    setSelB((b) => (b === id ? null : b));
    setMode("focus");
    setActive("B");
  }, []);
  const pickB = useCallback((id: string | null) => setSelB(id === selA ? null : id), [selA]);
  // One click fills the active slot; after A is chosen the B slot becomes active.
  const pick = useCallback((id: string) => (active === "A" || !selA ? pickA(id) : pickB(id)), [active, selA, pickA, pickB]);
  const clearSlot = useCallback((slot: Slot) => {
    if (slot === "A") {
      setSelA(selB);
      setSelB(null);
      setActive(selB ? "B" : "A");
    } else {
      setSelB(null);
      setActive("B");
    }
  }, [selB]);
  const swap = useCallback(() => {
    setSelA(selB);
    setSelB(selA);
  }, [selA, selB]);

  if (error !== null) return <div className="fatal">{t.loadError(error)}</div>;
  if (!bundle) return <div className="fatal">{t.loading}</div>;

  const { data, interp } = bundle;
  const v = views[view];
  const a = selA && tracks[selA] ? selA : null;
  const b = selB && tracks[selB] && selB !== a ? selB : null;

  return (
    <LangContext.Provider value={t}>
      <div className="app" style={{ ["--accent" as string]: VIEW_COLOR[view] }}>
        <header className="top">
          <div className="brand">
            <Logo />
            <div>
              <h1>SongWeave</h1>
              <span className="tagline">{t.tagline}</span>
            </div>
          </div>
          <div className="stats">
            {data.dataset.kind === "fixture" && <span className="fixture">{t.fixtureBadge}</span>}
            <span className="stat">
              <b>{data.dataset.track_count}</b> {t.statSongs}
            </span>
            <span className="stat">
              <b>5</b> {t.statDims}
            </span>
            <span className="stat model mono">{v.model_label}</span>
            <div className="seg lang" role="group" aria-label="Language">
              {LANGS.map((l) => (
                <button key={l} className={l === lang ? "on" : ""} aria-pressed={l === lang} onClick={() => setLang(l)}>
                  {l === "en" ? "EN" : "日本語"}
                </button>
              ))}
            </div>
          </div>
        </header>
        <nav className="views" role="tablist" aria-label="Dimensions">
          {VIEW_IDS.map((id) => (
            <button key={id} role="tab" aria-selected={id === view} className={`${id === view ? "active" : ""} ${views[id].status !== "ready" ? "dim" : ""}`} style={{ ["--c" as string]: VIEW_COLOR[id] }} onClick={() => setView(id)}>
              <span className="vt">
                <i className="vdot" />
                {viewName(t, id)}
                <small className="mono">{views[id].status === "ready" ? views[id].included.length : "—"}</small>
              </span>
              <span className="vd">{viewDesc(t, id)}</span>
            </button>
          ))}
        </nav>
        <main className="layout">
          <TrackList tracks={data.tracks} view={view} selA={a} selB={b} active={a ? active : "A"} rankingForA={a ? v.ranking?.[a] ?? null : null} onPick={pick} onActivate={setActive} onClear={clearSlot} onSwap={swap} />
          <section className="center">
            <MapView view={v} tracks={tracks} selA={a} selB={b} mode={mode} onMode={setMode} onPick={pick} onPickA={pickA} />
            {interp.failed_validation_count > 0 && <p className="notices">{t.failedHidden(interp.failed_validation_count)}</p>}
          </section>
          <aside className="side">
            {a ? (
              <PairPanel data={data} tracks={tracks} views={views} view={view} selA={a} selB={b} interps={interp.items} lang={lang} index={index} actions={{ play, setView }} onPickB={pickB} onSwap={swap} canGenerate={canGenerate} onRefresh={refreshInterp} />
            ) : (
              <section className="panel start">
                <h2>{t.startTitle}</h2>
                <p className="muted">{t.startBody}</p>
                <ol className="steps">
                  <li>
                    <b>1</b> {t.setA}
                  </li>
                  <li>
                    <b>2</b> {t.setB}
                  </li>
                  <li>
                    <b>3</b> ▶ {t.listenFor}
                  </li>
                </ol>
              </section>
            )}
          </aside>
        </main>
        <PlayerBar player={player} selA={a} />
      </div>
    </LangContext.Provider>
  );
}
