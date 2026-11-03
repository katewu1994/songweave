import type { ViewId } from "./types";

// One accent per dimension, used consistently in tabs, map, fingerprint and evidence.
export const VIEW_COLOR: Record<ViewId, string> = {
  overall_peav: "#8fa2ff",
  melody_merit: "#ff5fa8",
  rhythm_merit: "#ffcc33",
  timbre_merit: "#b583ff",
  lyrics_sonar: "#3ee09a",
};

export const COLOR_A = "#ff8a3d";
export const COLOR_B = "#3dd9ff";

/** Mix a hex colour toward a dim grey; t = 1 keeps the colour, t = 0 is grey. */
export function fade(hex: string, t: number, grey = [70, 78, 98]): string {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const k = Math.max(0, Math.min(1, t));
  const m = c.map((v, i) => Math.round(grey[i] + (v - grey[i]) * k));
  return `rgb(${m[0]}, ${m[1]}, ${m[2]})`;
}
