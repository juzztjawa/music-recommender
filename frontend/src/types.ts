// Mirrors the backend response shapes (app/agents/orchestrator.py, app/schemas/feedback.py).

export interface EvidenceItem {
  source: string;
  evidence_type: string;
  summary: string;
}

export interface RecommendedSong {
  title: string;
  artist: string;
  sources: string[];
  evidence: EvidenceItem[];
  recommendation_strength: number;
  variant: string;
  explanation: string;
}

export interface DiscoveryCluster {
  theme: string;
  hypothesis: string;
  input_songs: string[];
  recommendations: RecommendedSong[];
}

export interface AudioAnalysis {
  query: string;
  caption: string | null;
  source_url: string | null;
  error: string | null;
}

export interface DiscoveryResult {
  run_id?: string | null;
  thread_id?: string | null;
  // The supervisor's conversational message.
  reply: string;
  audio_analysis: AudioAnalysis[];
  clusters: DiscoveryCluster[];
}

export type Reaction = "loved_it" | "pretty_good" | "mixed" | "missed";

export interface RunSummary {
  run_id: string;
  created_at: string;
  title: string;
  thread_id: string | null;
  reaction: Reaction | null;
}

export interface ToolEvent {
  type: "tool";
  status: "started" | "done" | "error";
  name: string;
  call_id: string;
  args?: Record<string, unknown>;
  duration_ms?: number;
  summary?: string;
}

export type StreamEvent =
  | { type: "thread"; thread_id: string; run_id: string }
  | ToolEvent
  | { type: "message"; text: string }
  | { type: "result"; data: DiscoveryResult }
  | { type: "error"; message: string; retry_after?: number };

// null = not set by the user, so the agent decides (the message can say "live versions please").
export interface ChatOptions {
  include_live: boolean | null;
  include_covers: boolean | null;
  target_count: number | null;
}

export interface ThreadSummary {
  thread_id: string;
  title: string;
  updated_at: string;
  turns: number;
}

export interface StoredTurn {
  run_id: string;
  created_at: string;
  message: string;
  assistant_text: string | null;
  result: DiscoveryResult | null;
  status: "ok" | "reply" | "failed";
  reaction: Reaction | null;
}

export interface Thread {
  thread_id: string;
  turns: StoredTurn[];
}

export interface SpotifyOutcome {
  playlist_url: string;
  playlist_name: string;
  added: number;
  not_found: string[];
}
