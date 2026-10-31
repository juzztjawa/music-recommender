import { formatWait } from "../chat";
import type { ChatTurn } from "../chat";
import { Mark, WarnIcon } from "./Icons";
import ResultView from "./ResultView";
import ToolActivity from "./ToolActivity";

export function UserMessage({ text }: { text: string }) {
  return (
    <div className="msg user">
      <div className="bubble">{text}</div>
    </div>
  );
}

export function AssistantMessage({ turn, onRetry }: { turn: ChatTurn; onRetry?: () => void }) {
  const hasBatch = turn.result !== null && turn.result.clusters.length > 0;
  return (
    <div className="msg assistant">
      <div className="avatar">
        <Mark size={16} />
      </div>
      <div className="body">
        {(turn.status === "streaming" || turn.calls.length > 0) && <ToolActivity turn={turn} />}

        {turn.text && <p className="reply">{turn.text}</p>}

        {hasBatch && turn.result && (
          <ResultView result={turn.result} runId={turn.runId} reaction={turn.reaction} />
        )}

        {turn.status === "reply" && !turn.text && <p className="muted">No answer was recorded.</p>}

        {turn.status === "failed" && (
          <p className="notice">
            <WarnIcon /> This answer wasn't saved — the run didn't finish. Send the message again to
            retry.
          </p>
        )}

        {turn.status === "error" && (
          <div className="notice error-box" role="alert">
            <WarnIcon />
            <div>
              <div>
                {turn.error}
                {turn.retryAfter !== null && ` Try again in ${formatWait(turn.retryAfter)}.`}
              </div>
              {onRetry && turn.retryAfter === null && (
                <button className="link" onClick={onRetry}>
                  Try again
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
