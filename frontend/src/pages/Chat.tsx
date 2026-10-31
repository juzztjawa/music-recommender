import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { ApiError, api, streamChat } from "../api";
import { applyEvent, describeError, finishStream, newTurn, turnFromStored } from "../chat";
import type { ChatTurn } from "../chat";
import Composer, { DEFAULT_OPTIONS } from "../components/Composer";
import { Mark } from "../components/Icons";
import { AssistantMessage, UserMessage } from "../components/Message";
import type { ChatOptions } from "../types";
import type { ShellContext } from "./Shell";

const SUGGESTIONS = [
  "Songs like Made in Abyss by Kevin Penkin, but calmer",
  "Something with the late-night feel of Nujabes – Feather",
  "Paste a Spotify or YouTube link and tell me what you loved about it",
];

export default function Chat() {
  const { threadId: routeThread } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { refreshThreads } = useOutletContext<ShellContext>();

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [options, setOptions] = useState<ChatOptions>(DEFAULT_OPTIONS);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const abort = useRef<AbortController | null>(null);
  // Thread created by a send that is still on screen: navigating to it must not reload it.
  const liveThread = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  // Load a stored thread when the route changes; reset for "/".
  useEffect(() => {
    if (routeThread && routeThread === liveThread.current) return;
    liveThread.current = null;
    abort.current?.abort();
    setRunning(false);
    setTurns([]);
    setLoadError(null);
    stick.current = true;
    if (!routeThread) return;
    let cancelled = false;
    setLoading(true);
    api
      .thread(routeThread)
      .then((t) => !cancelled && setTurns(t.turns.map(turnFromStored)))
      .catch(
        (e) =>
          !cancelled &&
          setLoadError(
            e instanceof ApiError && e.status === 404
              ? "That conversation doesn't exist."
              : "Couldn't load this conversation.",
          ),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [routeThread, location.key]);

  useEffect(() => () => abort.current?.abort(), []);

  // Follow new content unless the reader scrolled up.
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [turns, loading]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  async function send(text: string) {
    const message = text.trim();
    if (!message || running) return;
    const key = crypto.randomUUID();
    const patch = (fn: (t: ChatTurn) => ChatTurn) =>
      setTurns((prev) => prev.map((t) => (t.key === key ? fn(t) : t)));

    const ctrl = new AbortController();
    abort.current = ctrl;
    stick.current = true;
    setDraft("");
    setRunning(true);
    setTurns((prev) => [...prev, newTurn(key, message, Date.now())]);
    const threadId = routeThread ?? liveThread.current;

    try {
      for await (const event of streamChat(message, threadId, options, ctrl.signal)) {
        if (event.type === "thread" && !threadId) {
          liveThread.current = event.thread_id;
          navigate(`/t/${event.thread_id}`);
        }
        patch((t) => applyEvent(t, event));
      }
      patch((t) => finishStream(t, Date.now()));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        patch((t) => ({ ...finishStream(t, Date.now()), status: "error", error: "Stopped." }));
      } else {
        const { message: m, retryAfter } = describeError(err);
        patch((t) => ({ ...t, status: "error", error: m, retryAfter }));
      }
    } finally {
      setRunning(false);
      refreshThreads();
    }
  }

  function retry(turn: ChatTurn) {
    setTurns((prev) => prev.filter((t) => t.key !== turn.key));
    void send(turn.message);
  }

  const empty = turns.length === 0 && !loading && !loadError;
  const lastKey = turns[turns.length - 1]?.key;

  return (
    <div className="chat">
      <div className="scroller" ref={scroller} onScroll={onScroll}>
        <div className="thread">
          {loading && <p className="muted center-msg">Loading conversation…</p>}
          {loadError && <p className="error center-msg">{loadError}</p>}

          {empty && (
            <div className="welcome">
              <span className="welcome-mark">
                <Mark size={34} />
              </span>
              <h1>What do you want to hear?</h1>
              <p className="muted">
                Tell me in your own words — songs you love, a link, or the feel you're after. Then
                steer: “a different artist”, “darker”, “hidden gems”.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggestion" onClick={() => setDraft(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t) => (
            <div key={t.key} className="turn">
              <UserMessage text={t.message} />
              <AssistantMessage
                turn={t}
                onRetry={t.key === lastKey && !running ? () => retry(t) : undefined}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="composer-wrap">
        <Composer
          draft={draft}
          setDraft={setDraft}
          running={running}
          onSend={() => void send(draft)}
          onStop={() => abort.current?.abort()}
          options={options}
          setOptions={setOptions}
          placeholder={turns.length ? "Ask for a change, or something new…" : "Message Orchestra…"}
        />
      </div>
    </div>
  );
}
