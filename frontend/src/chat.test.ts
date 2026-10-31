import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  applyEvent,
  describeError,
  finishStream,
  formatWait,
  groupThreads,
  newTurn,
  toolLabel,
  turnFromStored,
} from "./chat";
import type { DiscoveryResult, StoredTurn } from "./types";

const result = (clusters: DiscoveryResult["clusters"], reply = "Here you go"): DiscoveryResult => ({
  run_id: "run-1",
  thread_id: "t-1",
  reply,
  audio_analysis: [],
  clusters,
});
const cluster = { theme: "calm", hypothesis: "h", input_songs: [], recommendations: [] };
const t0 = () => newTurn("k", "hello", 1000);

describe("applyEvent", () => {
  it("merges overlapping tool calls by call_id", () => {
    let t = t0();
    t = applyEvent(t, { type: "tool", status: "started", name: "analyze_audio", call_id: "a", args: { song: "X" } });
    t = applyEvent(t, { type: "tool", status: "started", name: "resolve_song", call_id: "b" });
    t = applyEvent(t, { type: "tool", status: "done", name: "analyze_audio", call_id: "a", duration_ms: 50, summary: "ok" });
    expect(t.calls).toHaveLength(2);
    expect(t.calls[0]).toMatchObject({ status: "done", duration_ms: 50, args: { song: "X" } });
    expect(t.calls[1].status).toBe("started");
  });

  it("a non-empty result is a batch; an empty one is a text reply", () => {
    expect(applyEvent(t0(), { type: "result", data: result([cluster]) })).toMatchObject({ status: "ok", runId: "run-1" });
    expect(applyEvent(t0(), { type: "result", data: result([], "Just chatting") })).toMatchObject({
      status: "reply",
      text: "Just chatting",
    });
  });

  it("carries retry_after on errors", () => {
    expect(applyEvent(t0(), { type: "error", message: "Discovery limit reached.", retry_after: 600 })).toMatchObject({
      status: "error",
      retryAfter: 600,
    });
  });
});

describe("finishStream", () => {
  it("errors when nothing arrived, settles to reply when text did", () => {
    expect(finishStream(t0(), 2000)).toMatchObject({ status: "error", durationMs: 1000 });
    expect(finishStream({ ...t0(), text: "hi" }, 2000).status).toBe("reply");
  });
  it("leaves finished turns alone", () => {
    expect(finishStream({ ...t0(), status: "ok" }, 2000).status).toBe("ok");
  });
});

describe("turnFromStored", () => {
  const base: StoredTurn = {
    run_id: "r", created_at: "2026-10-31T00:00:00Z", message: "m", assistant_text: "a",
    result: null, status: "reply", reaction: null,
  };
  it("maps reply, failed and ok", () => {
    expect(turnFromStored(base)).toMatchObject({ status: "reply", text: "a" });
    expect(turnFromStored({ ...base, status: "failed", assistant_text: null }).status).toBe("failed");
    expect(turnFromStored({ ...base, status: "ok", result: result([cluster]), reaction: "mixed" })).toMatchObject({
      status: "ok", reaction: "mixed", text: "Here you go",
    });
  });
});

describe("helpers", () => {
  it("describes a 429 with its retry time", () => {
    expect(describeError(new ApiError(429, "x", 120))).toEqual({ message: expect.any(String), retryAfter: 120 });
    expect(describeError(new Error("boom")).retryAfter).toBeNull();
  });
  it("formats waits", () => {
    expect(formatWait(30)).toBe("a minute");
    expect(formatWait(600)).toBe("about 10 min");
    expect(formatWait(7200)).toBe("about 2 h");
  });
  it("labels known and unknown tools", () => {
    expect(toolLabel("retrieve_candidates")).toBe("Searching across sources");
    expect(toolLabel("brand_new_tool")).toBe("Brand new tool");
  });
  it("groups threads by recency", () => {
    const now = new Date("2026-10-31T15:00:00");
    const th = (id: string, iso: string) => ({ thread_id: id, title: id, updated_at: iso, turns: 1 });
    const groups = groupThreads(
      [th("a", "2026-10-31T09:00:00"), th("b", "2026-10-30T20:00:00"), th("c", "2026-10-27T10:00:00"), th("d", "2026-09-01T10:00:00")],
      now,
    );
    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday", "Previous 7 days", "Older"]);
  });
});
