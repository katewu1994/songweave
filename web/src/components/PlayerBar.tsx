import { useEffect, useState } from "react";
import { mmss } from "../data";
import { useT } from "../i18n";
import type { PlayerState, SegmentPlayer } from "../player";
import { COLOR_A, COLOR_B } from "../theme";

export function PlayerBar({ player, selA }: { player: SegmentPlayer; selA: string | null }) {
  const t = useT();
  const [s, setS] = useState<PlayerState | null>(null);
  useEffect(() => player.subscribe(setS), [player]);
  // The bar only appears once something has been played.
  if (!s?.request) return null;
  const { segment, label, alternate } = s.request;
  const len = segment.end - segment.start;
  const pct = Math.min(100, Math.max(0, ((s.position - segment.start) / len) * 100));
  const color = segment.track_id === selA ? COLOR_A : COLOR_B;
  return (
    <footer className="player" data-playing={s.playing ? "1" : "0"} style={{ ["--pc" as string]: color }}>
      <button className="round" onClick={() => (s.playing ? player.pause() : player.resume())} aria-label={s.playing ? t.pause : t.play}>
        {s.playing ? "❚❚" : "▶"}
      </button>
      <button className="round ghost" onClick={() => player.stop()} aria-label={t.stop}>
        ■
      </button>
      <div className="player-info">
        <div className="player-label">
          <span className={`eq${s.playing ? " on" : ""}`} aria-hidden>
            <i />
            <i />
            <i />
          </span>
          {label}
        </div>
        <div className="progress">
          <div style={{ width: `${pct}%` }} />
        </div>
        <div className="player-time mono" data-testid="player-time">
          {mmss(s.position)} / {t.segment} {mmss(segment.start)}–{mmss(segment.end)}
        </div>
      </div>
      {alternate && (
        <button className="ab" onClick={() => player.toggleAB()} title={t.switchTo(alternate.label)}>
          {t.abSwitch}
        </button>
      )}
      {s.error && <span className="warn">{s.error === "blocked" ? t.playBlocked : t.playError}</span>}
    </footer>
  );
}
