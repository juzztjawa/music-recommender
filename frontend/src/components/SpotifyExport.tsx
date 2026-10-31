import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api";
import type { SpotifyOutcome } from "../types";

const FLASH: Record<string, string> = {
  connected: "Spotify connected — press Export to Spotify to create the playlist.",
  denied: "Spotify access was declined.",
  error: "Couldn't connect Spotify. Try again.",
};

export default function SpotifyExport({ runId }: { runId: string }) {
  const [params] = useSearchParams();
  // The OAuth return carries ?spotify=…&run=<id>; only that batch shows the message.
  const flash = params.get("run") === runId ? FLASH[params.get("spotify") ?? ""] : undefined;
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<SpotifyOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsReconnect, setNeedsReconnect] = useState(false);

  async function connect() {
    const { url } = await api.spotifyConnect(runId);
    window.location.href = url;
  }

  async function exportNow() {
    setBusy(true);
    setError(null);
    setNeedsReconnect(false);
    try {
      if (!(await api.spotifyStatus()).connected) return await connect();
      setOutcome(await api.exportSpotify(runId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setNeedsReconnect(true);
      setError(err instanceof ApiError ? err.message : "Export failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="ghost spotify" disabled={busy} onClick={exportNow}>
        {busy ? "Working…" : "Export to Spotify"}
      </button>
      {flash && !outcome && <span className="muted note">{flash}</span>}
      {error && <span className="error note">{error}</span>}
      {needsReconnect && (
        <button className="ghost" onClick={() => connect().catch(() => setError("Couldn't start Spotify login."))}>
          Reconnect Spotify
        </button>
      )}
      {outcome && (
        <div className="note-block">
          Added {outcome.added} songs to{" "}
          <a href={outcome.playlist_url} target="_blank" rel="noreferrer">
            {outcome.playlist_name}
          </a>
          .
          {outcome.not_found.length > 0 && (
            <details>
              <summary>{outcome.not_found.length} not found on Spotify</summary>
              <ul>
                {outcome.not_found.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </>
  );
}
