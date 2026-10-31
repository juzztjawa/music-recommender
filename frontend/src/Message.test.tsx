import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { applyEvent, newTurn } from "./chat";
import type { ChatTurn } from "./chat";
import { AssistantMessage } from "./components/Message";
import type { DiscoveryResult } from "./types";

const render = (turn: ChatTurn) =>
  renderToString(
    <MemoryRouter>
      <AssistantMessage turn={turn} onRetry={() => {}} />
    </MemoryRouter>,
  );

const song = {
  title: "Hoshi", artist: "Someone", sources: ["spotify"], evidence: [{ source: "reddit", evidence_type: "x", summary: "fans link them" }],
  recommendation_strength: 0.8, variant: "original", explanation: "Shares the swelling strings.",
};
const batch: DiscoveryResult = {
  run_id: "r1", thread_id: "t1", reply: "Here are some picks.",
  audio_analysis: [{ query: "Made in Abyss", caption: null, source_url: null, error: "not hosted" }],
  clusters: [{ theme: "calm orchestral", hypothesis: "h", input_songs: ["Made in Abyss"], recommendations: [song] }],
};
const turn = () => newTurn("k", "hi", Date.now());

describe("AssistantMessage states", () => {
  it("loading: shows thinking, no results", () => {
    const html = render(turn());
    expect(html).toContain("Thinking");
  });

  it("streaming with tool calls lists them", () => {
    const html = render(
      applyEvent(turn(), { type: "tool", status: "started", name: "retrieve_candidates", call_id: "1" }),
    );
    expect(html).toContain("Searching across sources");
  });

  it("batch: renders clusters, songs, actions and the audio note", () => {
    const html = render(applyEvent(turn(), { type: "result", data: batch }));
    expect(html).toContain("calm orchestral");
    expect(html).toContain("Hoshi");
    expect(html).toContain("Export to Spotify");
    expect(html).toContain("How was this batch?");
    expect(html).toContain("Audio wasn&#x27;t analysed");
  });

  it("empty cluster shows the filter message; text-only reply has no actions", () => {
    const empty = { ...batch, clusters: [{ ...batch.clusters[0], recommendations: [] }] };
    expect(render(applyEvent(turn(), { type: "result", data: empty }))).toContain("Nothing passed the filters");
    const reply = render(applyEvent(turn(), { type: "result", data: { ...batch, clusters: [], reply: "Which song?" } }));
    expect(reply).toContain("Which song?");
    expect(reply).not.toContain("Export to Spotify");
  });

  it("error: 429-style message with wait time and no retry button; generic error offers retry", () => {
    const limited = render(applyEvent(turn(), { type: "error", message: "Discovery limit reached.", retry_after: 1800 }));
    expect(limited).toContain("about 30 min");
    expect(limited).not.toContain("Try again</button>");
    expect(render(applyEvent(turn(), { type: "error", message: "Discovery failed." }))).toContain("Try again</button>");
  });

  it("failed stored turn explains itself", () => {
    expect(render({ ...turn(), status: "failed" })).toContain("didn&#x27;t finish");
  });
});
