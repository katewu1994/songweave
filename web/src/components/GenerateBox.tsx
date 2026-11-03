import { useState } from "react";
import { useT, type Lang } from "../i18n";

interface Preview {
  job_id: string;
  cached: boolean;
  model: string;
}

const HEADERS = { "Content-Type": "application/json", "X-SongWeave": "1" };

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: HEADERS, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { error?: string }).error ?? `HTTP ${r.status}`);
  return data as T;
}

/**
 * Explicit, per-pair generation: click → preview of what will be sent → confirm. Nothing is sent
 * until the user confirms, and only for this pair.
 */
export function GenerateBox({ a, b, lang, fallback, onDone }: { a: string; b: string; lang: Lang; fallback: boolean; onDone: () => Promise<void> }) {
  const t = useT();
  const [stage, setStage] = useState<"idle" | "preview" | "running">("idle");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    try {
      const p = await post<Preview>("/api/generate/preview", { a, b, lang });
      setPreview(p);
      if (p.cached) {
        await onDone();
        setStage("idle");
      } else setStage("preview");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const send = async () => {
    if (!preview) return;
    setStage("running");
    setError(null);
    try {
      await post("/api/generate", { a, b, lang, confirm_job_id: preview.job_id });
      await onDone();
      setStage("idle");
    } catch (e) {
      setError((e as Error).message);
      setStage("preview");
    }
  };

  return (
    <div className="gen-box">
      {stage === "idle" && (
        <button className="gen-btn" onClick={start}>
          <span className="ai-dot" /> {fallback ? t.genInLang : t.genButton}
        </button>
      )}
      {stage !== "idle" && preview && (
        <div className="gen-preview">
          <p>{t.genPreviewTitle(preview.model)}</p>
          <ul>
            <li>✓ {t.genScopeIds}</li>
            <li>✓ {t.genScopeNumbers}</li>
            <li className="muted">✕ {t.genScopeNot}</li>
          </ul>
          {stage === "preview" ? (
            <div className="gen-actions">
              <button className="gen-btn" onClick={send}>
                {t.genSend}
              </button>
              <button className="ghost" onClick={() => setStage("idle")}>
                {t.genCancel}
              </button>
            </div>
          ) : (
            <p className="gen-running">
              <span className="spinner" /> {t.genRunning}
            </p>
          )}
        </div>
      )}
      {error && <p className="warn small">{t.genFailed(error)}</p>}
    </div>
  );
}
