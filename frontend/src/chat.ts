// Pure chat state: how a turn evolves as stream events arrive, and how stored
// turns map onto the same shape. No React in here so it is unit-testable.

import { ApiError } from "./api";
import type {
  DiscoveryResult,
  Reaction,
  StoredTurn,
  StreamEvent,
  ThreadSummary,
  ToolEvent,
} from "./types";

export type ToolCall = Pick<ToolEvent, "call_id" | "name" | "status" | "duration_ms" | "summary" | "args">;

export type TurnStatus = "streaming" | "ok" | "reply" | "failed" | "error";

export interface ChatTurn {
  key: string;
  message: string;
  status: TurnStatus;
  calls: ToolCall[];
  /** The assistant's words (a text-only answer, or the intro to a batch). */
  text: string | null;
  result: DiscoveryResult | null;
  error: string | null;
  retryAfter: number | null;
  runId: string | null;
  reaction: Reaction | null;
  startedAt: number | null;
  durationMs: number | null;
}

export function newTurn(key: string, message: string, now: number): ChatTurn {
  return {
    key,
    message,
    status: "streaming",
    calls: [],
    text: null,
    result: null,
    error: null,
    retryAfter: null,
    runId: null,
    reaction: null,
    startedAt: now,
    durationMs: null,
  };
}

export function applyEvent(turn: ChatTurn, event: StreamEvent): ChatTurn {
  switch (event.type) {
    case "thread":
      return { ...turn, runId: event.run_id };
    case "tool": {
      const known = turn.calls.some((c) => c.call_id === event.call_id);
      const call: ToolCall = {
        call_id: event.call_id,
        name: event.name,
        status: event.status,
        duration_ms: event.duration_ms,
        summary: event.summary,
        args: event.args,
      };
      return {
        ...turn,
        calls: known
          ? turn.calls.map((c) =>
              c.call_id === event.call_id ? { ...c, ...stripUndefined(call) } : c,
            )
          : [...turn.calls, call],
      };
    }
    case "message":
      return { ...turn, text: event.text };
    case "result": {
      const result = event.data;
      return {
        ...turn,
        result,
        text: result.reply || turn.text,
        status: result.clusters.length > 0 ? "ok" : "reply",
        runId: result.run_id ?? turn.runId,
      };
    }
    case "error":
      return {
        ...turn,
        status: "error",
        error: event.message,
        retryAfter: event.retry_after ?? null,
      };
  }
}

function stripUndefined<T extends object>(obj: T): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as Partial<T>;
}

/** Called when the stream ends: settle a turn that never got a result/error. */
export function finishStream(turn: ChatTurn, now: number): ChatTurn {
  const durationMs = turn.startedAt ? now - turn.startedAt : null;
  if (turn.status !== "streaming") return { ...turn, durationMs };
  if (turn.text) return { ...turn, status: "reply", durationMs };
  return {
    ...turn,
    status: "error",
    error: "The connection closed before an answer arrived.",
    durationMs,
  };
}

export function turnFromStored(t: StoredTurn): ChatTurn {
  return {
    ...newTurn(t.run_id, t.message, 0),
    status: t.status === "ok" ? "ok" : t.status === "reply" ? "reply" : "failed",
    text: t.result?.reply || t.assistant_text,
    result: t.result,
    runId: t.run_id,
    reaction: t.reaction,
    startedAt: null,
  };
}

export function formatWait(seconds: number): string {
  if (seconds < 90) return "a minute";
  const mins = Math.ceil(seconds / 60);
  return mins >= 90 ? `about ${Math.ceil(mins / 60)} h` : `about ${mins} min`;
}

/** User-facing text for a failure before the stream started (HTTP error). */
export function describeError(err: unknown): { message: string; retryAfter: number | null } {
  if (err instanceof ApiError && err.status === 429) {
    return {
      message: "You're sending messages too quickly.",
      retryAfter: err.retryAfter ?? null,
    };
  }
  if (err instanceof ApiError && err.status === 422) {
    return { message: "That message can't be sent (empty or too long).", retryAfter: null };
  }
  return { message: "Something went wrong. Please try again.", retryAfter: null };
}

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

/** Sidebar grouping: Today / Yesterday / Previous 7 days / Older (input is newest first). */
export function groupThreads(
  threads: ThreadSummary[],
  now: Date,
): { label: string; items: ThreadSummary[] }[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets: [string, ThreadSummary[]][] = [
    ["Today", []],
    ["Yesterday", []],
    ["Previous 7 days", []],
    ["Older", []],
  ];
  for (const t of threads) {
    const age = startOfToday - new Date(t.updated_at).getTime();
    const i = age <= 0 ? 0 : age <= DAY ? 1 : age <= 7 * DAY ? 2 : 3;
    buckets[i][1].push(t);
  }
  return buckets.filter(([, items]) => items.length > 0).map(([label, items]) => ({ label, items }));
}

const TOOL_LABELS: Record<string, string> = {
  get_session_history: "Remembering this conversation",
  resolve_song: "Identifying the song",
  analyze_audio: "Listening to the audio",
  retrieve_candidates: "Searching across sources",
  select_and_diversify: "Picking and diversifying",
  write_explanations: "Writing the explanations",
};

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  const words = name.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Working";
}

/** A short detail for a running tool, e.g. the song being looked up. */
export function toolDetail(call: ToolCall): string | null {
  const v = Object.values(call.args ?? {}).find((x) => typeof x === "string" && x.length > 0);
  return typeof v === "string" ? (v.length > 60 ? `${v.slice(0, 57)}…` : v) : null;
}
