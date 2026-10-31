import { describe, expect, it } from "vitest";
import { createSSEParser } from "./sse";

const frame = (obj: object) => `event: ${(obj as { type: string }).type}\ndata: ${JSON.stringify(obj)}\n\n`;

describe("createSSEParser", () => {
  it("parses whole frames", () => {
    const parse = createSSEParser();
    const out = parse(frame({ type: "thread", thread_id: "t", run_id: "r" }) + frame({ type: "message", text: "hi" }));
    expect(out.map((e) => e.type)).toEqual(["thread", "message"]);
  });

  it("buffers a frame split across chunks, including mid-CRLF", () => {
    const parse = createSSEParser();
    const raw = frame({ type: "message", text: "héllo" }).replace(/\n/g, "\r\n");
    const out = [...raw].flatMap((ch) => parse(ch)); // one character at a time
    expect(out).toEqual([{ type: "message", text: "héllo" }]);
  });

  it("skips malformed and data-less frames without breaking later ones", () => {
    const parse = createSSEParser();
    const out = parse(": keepalive\n\n" + "event: x\ndata: {not json\n\n" + frame({ type: "message", text: "ok" }));
    expect(out).toEqual([{ type: "message", text: "ok" }]);
  });

  it("accepts `data:` without a space", () => {
    expect(createSSEParser()('data:{"type":"message","text":"a"}\n\n')).toHaveLength(1);
  });
});
