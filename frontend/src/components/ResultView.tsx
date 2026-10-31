import { useState } from "react";
import { api } from "../api";
import type { DiscoveryResult, Reaction, RecommendedSong } from "../types";
import { DownloadIcon } from "./Icons";
import FeedbackBar from "./FeedbackBar";
import SpotifyExport from "./SpotifyExport";

function SongRow({ song, index }: { song: RecommendedSong; index: number }) {
  const [open, setOpen] = useState(false);
  const link = `https://www.youtube.com/results?search_query=${encodeURIComponent(
    `${song.title} ${song.artist}`,
  )}`;
  const pct = Math.round(song.recommendation_strength * 100);
  return (
    <li className="song">
      <span className="song-n tabular">{String(index + 1).padStart(2, "0")}</span>
      <div className="song-main">
        <div className="song-head">
          <a href={link} target="_blank" rel="noreferrer" className="song-title">
            {song.title}
          </a>
          <span className="song-artist">{song.artist}</span>
          {song.variant !== "original" && <span className="tag">{song.variant}</span>}
          <span className="strength" title={`Match strength ${pct}%`}>
            <span style={{ width: `${pct}%` }} />
          </span>
        </div>
        <p className="song-why">{song.explanation}</p>
        {song.evidence.length > 0 && (
          <>
            <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? "Hide evidence" : `Evidence (${song.evidence.length})`}
            </button>
            {open && (
              <ul className="evidence">
                {song.evidence.map((e, i) => (
                  <li key={i}>
                    <span className="tag">{e.source}</span> {e.summary}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </li>
  );
}

export default function ResultView({
  result,
  runId,
  reaction,
}: {
  result: DiscoveryResult;
  runId: string | null;
  reaction: Reaction | null;
}) {
  const failedAudio = result.audio_analysis.filter((a) => a.caption === null);
  return (
    <div className="result">
      {result.clusters.map((c) => (
        <section key={c.theme} className="cluster">
          <h3>{c.theme}</h3>
          {c.input_songs.length > 0 && <p className="muted cluster-from">From {c.input_songs.join(" · ")}</p>}
          {c.recommendations.length === 0 ? (
            <p className="muted">Nothing passed the filters for this theme.</p>
          ) : (
            <ol className="songs">
              {c.recommendations.map((s, i) => (
                <SongRow key={`${s.title}::${s.artist}`} song={s} index={i} />
              ))}
            </ol>
          )}
        </section>
      ))}

      {failedAudio.length > 0 && (
        <p className="muted fine">
          Audio wasn't analysed for {failedAudio.map((a) => `“${a.query}”`).join(", ")}; these picks
          lean on text evidence.
        </p>
      )}

      {runId && (
        <div className="actions">
          <div className="action-row">
            <button className="ghost" onClick={() => api.downloadExport(runId, "csv")}>
              <DownloadIcon /> CSV
            </button>
            <button className="ghost" onClick={() => api.downloadExport(runId, "json")}>
              <DownloadIcon /> JSON
            </button>
            <SpotifyExport runId={runId} />
          </div>
          <FeedbackBar runId={runId} initial={reaction} />
        </div>
      )}
    </div>
  );
}
