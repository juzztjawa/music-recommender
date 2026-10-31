import type { StreamEvent } from "./types";

/**
 * Incremental Server-Sent-Events parser. Frames are separated by a blank
 * line; the payload is the `data:` line(s). Chunks can split a frame (or a
 * CRLF) anywhere, so leftover text is buffered until the frame completes.
 * Malformed frames are skipped rather than killing the stream.
 */
export function createSSEParser(): (chunk: string) => StreamEvent[] {
  let buffer = "";
  return (chunk) => {
    buffer = (buffer + chunk).replace(/\r\n/g, "\n");
    const events: StreamEvent[] = [];
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (!data) continue;
      try {
        events.push(JSON.parse(data) as StreamEvent);
      } catch {
        /* skip a malformed frame */
      }
    }
    return events;
  };
}
