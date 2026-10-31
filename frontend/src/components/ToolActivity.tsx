import { useEffect, useState } from "react";
import { toolDetail, toolLabel } from "../chat";
import type { ChatTurn } from "../chat";
import { CheckIcon, ChevronIcon, WarnIcon } from "./Icons";

function useElapsed(startedAt: number | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;
}

const fmt = (s: number) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`);

/** Live view of what the agent is doing; folds into a one-line summary once done. */
export default function ToolActivity({ turn }: { turn: ChatTurn }) {
  const streaming = turn.status === "streaming";
  const elapsed = useElapsed(turn.startedAt, streaming);
  const [open, setOpen] = useState(false);
  const showList = streaming || open;
  const total = turn.durationMs !== null ? Math.round(turn.durationMs / 1000) : elapsed;

  return (
    <div className={`activity ${streaming ? "live" : ""}`}>
      <button
        type="button"
        className="activity-head"
        onClick={() => setOpen(!open)}
        disabled={streaming}
        aria-expanded={showList}
      >
        {streaming ? (
          <span className="eq" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        ) : (
          <span className={`chev ${open ? "open" : ""}`}>
            <ChevronIcon />
          </span>
        )}
        <span>
          {streaming
            ? turn.calls.length === 0
              ? "Thinking"
              : "Working"
            : `Worked for ${fmt(total)} · ${turn.calls.length} step${turn.calls.length === 1 ? "" : "s"}`}
        </span>
        {streaming && <span className="muted tabular">{fmt(elapsed)}</span>}
      </button>

      {showList && turn.calls.length > 0 && (
        <ol className="steps">
          {turn.calls.map((c) => {
            const detail = toolDetail(c);
            return (
              <li key={c.call_id} className={c.status}>
                <span className="step-mark">
                  {c.status === "done" ? (
                    <CheckIcon />
                  ) : c.status === "error" ? (
                    <WarnIcon />
                  ) : (
                    <span className="spinner" />
                  )}
                </span>
                <span className="step-label">
                  {toolLabel(c.name)}
                  {detail && <span className="muted"> · {detail}</span>}
                  {c.status === "error" && <span className="muted"> — hit a snag, carrying on</span>}
                </span>
                {c.duration_ms !== undefined && (
                  <span className="muted tabular">{(c.duration_ms / 1000).toFixed(1)}s</span>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {streaming && elapsed >= 45 && (
        <p className="muted hint">Searching properly takes a few minutes — you can keep this tab open.</p>
      )}
    </div>
  );
}
