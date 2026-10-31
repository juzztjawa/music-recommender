import { useState } from "react";
import { api } from "../api";
import type { Reaction } from "../types";

export const REACTION_LABELS: Record<Reaction, string> = {
  loved_it: "Loved it",
  pretty_good: "Pretty good",
  mixed: "Mixed",
  missed: "Missed the mark",
};

// FR-13: lightweight, batch-level feedback with an optional comment.
export default function FeedbackBar({
  runId,
  initial,
}: {
  runId: string;
  initial: Reaction | null;
}) {
  const [reaction, setReaction] = useState<Reaction | null>(initial);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(initial !== null);
  const [error, setError] = useState(false);

  async function send(r: Reaction, c: string) {
    setReaction(r);
    setError(false);
    try {
      await api.feedback(runId, r, c);
      setSaved(true);
    } catch {
      setSaved(false);
      setError(true);
    }
  }

  return (
    <div className="feedback">
      <span className="muted">How was this batch?</span>
      <div className="chips">
        {(Object.keys(REACTION_LABELS) as Reaction[]).map((r) => (
          <button
            key={r}
            className={reaction === r ? "chip active" : "chip"}
            onClick={() => send(r, comment)}
          >
            {REACTION_LABELS[r]}
          </button>
        ))}
      </div>
      {reaction && (
        <div className="comment">
          <textarea
            rows={2}
            maxLength={2000}
            placeholder="Anything to add? (optional)"
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
              setSaved(false);
            }}
          />
          <button className="ghost" disabled={saved || !comment.trim()} onClick={() => send(reaction, comment)}>
            {saved ? "Saved" : "Save comment"}
          </button>
          {error && <span className="error">Couldn't save — try again.</span>}
        </div>
      )}
    </div>
  );
}
