import { createSSEParser } from "./sse";
import type {
  ChatOptions,
  DiscoveryResult,
  Reaction,
  RunSummary,
  SpotifyOutcome,
  StreamEvent,
  Thread,
  ThreadSummary,
} from "./types";

const TOKEN_KEY = "orchestra.token";

export const tokenStore = {
  get: (): string | null => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage blocked: session lasts until reload */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

// Set by the auth provider so any 401 drops the user back to login.
let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

async function toError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    /* non-JSON error body */
  }
  const retry = res.headers.get("Retry-After");
  return new ApiError(res.status, detail, retry ? Number(retry) : undefined);
}

async function request(path: string, init: RequestInit = {}, auth = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (res.status === 401 && auth) onUnauthorized();
  if (!res.ok) throw await toError(res);
  return res;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // `dev_link` is only present when the backend runs with ENVIRONMENT=test.
  requestLink: async (email: string): Promise<{ dev_link?: string }> =>
    (await request("/auth/request-link", { method: "POST", body: json({ email }) }, false)).json(),

  verify: async (token: string): Promise<string> => {
    const res = await request("/auth/verify", { method: "POST", body: json({ token }) }, false);
    return (await res.json()).access_token;
  },

  me: async (): Promise<{ id: string; email: string }> => (await request("/auth/me")).json(),

  threads: async (): Promise<ThreadSummary[]> => (await request("/threads")).json(),

  thread: async (threadId: string): Promise<Thread> =>
    (await request(`/threads/${threadId}`)).json(),

  runs: async (): Promise<RunSummary[]> => (await request("/runs")).json(),

  run: async (runId: string): Promise<DiscoveryResult> => (await request(`/runs/${runId}`)).json(),

  feedback: (run_id: string, reaction: Reaction, comment: string) =>
    request("/feedback", {
      method: "POST",
      body: json({ run_id, reaction, comment: comment.trim() || null }),
    }),

  spotifyStatus: async (): Promise<{ connected: boolean }> =>
    (await request("/spotify/status")).json(),

  // The SPA navigates to the returned Spotify consent URL (a plain redirect
  // from the API couldn't carry the auth header).
  spotifyConnect: async (runId: string): Promise<{ url: string }> =>
    (await request(`/spotify/connect?run_id=${runId}`)).json(),

  exportSpotify: async (runId: string): Promise<SpotifyOutcome> =>
    (await request(`/runs/${runId}/export/spotify`, { method: "POST", body: json({}) })).json(),

  // Authenticated downloads can't be a plain <a href>, so fetch and save the blob.
  downloadExport: async (runId: string, format: "csv" | "json") => {
    const res = await request(`/runs/${runId}/export?format=${format}`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `orchestra-${runId}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  },
};

/**
 * POST /chat/stream and yield its SSE events.
 * EventSource can't send POST bodies or auth headers, so the stream is read
 * by hand: events are separated by a blank line, payload is the `data:` line.
 */
/**
 * POST /chat/stream and yield its SSE events. EventSource can't send POST
 * bodies or auth headers, so the stream is read by hand (see sse.ts).
 */
export async function* streamChat(
  message: string,
  threadId: string | null,
  options: ChatOptions,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await request("/chat/stream", {
    method: "POST",
    body: json({ message, thread_id: threadId, ...options }),
    signal,
  });
  if (!res.body) throw new ApiError(500, "Streaming is not supported by this browser");

  const parse = createSSEParser();
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    yield* parse(value);
  }
}
