import type { Segment } from "./types";

export interface PlayRequest {
  segment: Segment;
  label: string;
  /** Optional counterpart for A/B switching (same evidence, other song). */
  alternate?: { segment: Segment; label: string };
}

export interface PlayerState {
  request: PlayRequest | null;
  playing: boolean;
  position: number; // seconds on the real song timeline
  error: "blocked" | "failed" | null;
}

type Listener = (s: PlayerState) => void;

/**
 * One audio element for the whole app, so only one source is ever audible. Segments play from
 * their real start and stop at their real end; the time base is the original file.
 */
export class SegmentPlayer {
  private audio: HTMLAudioElement;
  private state: PlayerState = { request: null, playing: false, position: 0, error: null };
  private listeners = new Set<Listener>();
  private raf = 0;
  private mediaUrl: (trackId: string) => string;

  constructor(mediaUrl: (trackId: string) => string, audio?: HTMLAudioElement) {
    this.mediaUrl = mediaUrl;
    this.audio = audio ?? new Audio();
    this.audio.preload = "auto";
    this.audio.addEventListener("pause", () => this.set({ playing: false }));
    this.audio.addEventListener("playing", () => this.set({ playing: true, error: null }));
    this.audio.addEventListener("error", () => this.set({ playing: false, error: "failed" }));
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<PlayerState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l(this.state));
  }

  async play(req: PlayRequest): Promise<void> {
    const seg = req.segment;
    if (!(seg.end > seg.start)) throw new Error("invalid segment");
    cancelAnimationFrame(this.raf);
    this.audio.pause();
    const url = this.mediaUrl(seg.track_id);
    if (!this.audio.src.endsWith(url)) {
      this.audio.src = url;
      await new Promise<void>((resolve, reject) => {
        const ok = () => {
          cleanup();
          resolve();
        };
        const bad = () => {
          cleanup();
          reject(new Error("load failed"));
        };
        const cleanup = () => {
          this.audio.removeEventListener("loadedmetadata", ok);
          this.audio.removeEventListener("error", bad);
        };
        this.audio.addEventListener("loadedmetadata", ok);
        this.audio.addEventListener("error", bad);
        this.audio.load();
      });
    }
    this.audio.currentTime = seg.start;
    this.set({ request: req, position: seg.start, error: null });
    try {
      await this.audio.play();
    } catch {
      this.set({ playing: false, error: "blocked" });
      return;
    }
    this.startTick(seg);
  }

  private startTick(seg: Segment) {
    cancelAnimationFrame(this.raf);
    const tick = () => {
      const t = this.audio.currentTime;
      if (t >= seg.end - 0.01) {
        this.audio.pause();
        this.audio.currentTime = seg.end;
        this.set({ position: seg.end, playing: false });
        return;
      }
      this.set({ position: t });
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  /** Switch to the other song of the same evidence, starting at its own real start time. */
  async toggleAB(): Promise<void> {
    const r = this.state.request;
    if (!r?.alternate) return;
    await this.play({ segment: r.alternate.segment, label: r.alternate.label, alternate: { segment: r.segment, label: r.label } });
  }

  pause() {
    cancelAnimationFrame(this.raf);
    this.audio.pause();
  }

  async resume() {
    const r = this.state.request;
    if (!r) return;
    if (this.audio.currentTime >= r.segment.end - 0.05 || this.audio.currentTime < r.segment.start) return this.play(r);
    try {
      await this.audio.play();
    } catch {
      this.set({ playing: false, error: "blocked" });
      return;
    }
    this.startTick(r.segment);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.audio.pause();
    this.set({ request: null, playing: false });
  }
}
