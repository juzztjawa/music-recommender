import { useEffect, useState } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";

/**
 * Spotify's OAuth return lands on /runs/:id?spotify=…. Threads are the unit
 * now, so look up the run's thread and forward, keeping the flash message.
 * A pre-thread run is its own one-turn thread (thread id == run id).
 */
export default function RunRedirect() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    api
      .run(runId)
      .then((r) => r.thread_id ?? runId)
      .catch(() => runId)
      .then((threadId) => {
        const q = new URLSearchParams({ run: runId });
        const spotify = params.get("spotify");
        if (spotify) q.set("spotify", spotify);
        setTarget(`/t/${threadId}?${q}`);
      });
  }, [runId, params]);

  return target ? <Navigate to={target} replace /> : <p className="muted center-msg">Opening…</p>;
}
