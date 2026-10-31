import { NavLink } from "react-router-dom";
import { groupThreads } from "../chat";
import type { ThreadSummary } from "../types";
import { LogoutIcon, Mark, PlusIcon } from "./Icons";

export default function Sidebar({
  threads,
  loadError,
  email,
  onLogout,
  onNavigate,
}: {
  threads: ThreadSummary[] | null;
  loadError: boolean;
  email: string;
  onLogout: () => void;
  onNavigate: () => void;
}) {
  const groups = threads ? groupThreads(threads, new Date()) : [];
  return (
    <aside className="sidebar" aria-label="Conversations">
      <div className="side-top">
        <span className="brand">
          <Mark /> Orchestra
        </span>
      </div>
      <NavLink to="/" end className="new-chat" onClick={onNavigate} state={{ fresh: Date.now() }}>
        <PlusIcon /> New chat
      </NavLink>

      <nav className="threads">
        {threads === null && !loadError && <p className="muted pad">Loading…</p>}
        {loadError && <p className="error pad">Couldn't load your history.</p>}
        {threads?.length === 0 && <p className="muted pad">Your conversations will show up here.</p>}
        {groups.map((g) => (
          <div key={g.label} className="group">
            <h4>{g.label}</h4>
            {g.items.map((t) => (
              <NavLink
                key={t.thread_id}
                to={`/t/${t.thread_id}`}
                className={({ isActive }) => `thread-link ${isActive ? "active" : ""}`}
                onClick={onNavigate}
                title={t.title}
              >
                {t.title}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="side-bottom">
        <span className="who" title={email}>
          {email}
        </span>
        <button className="icon-btn" onClick={onLogout} aria-label="Sign out" title="Sign out">
          <LogoutIcon />
        </button>
      </div>
    </aside>
  );
}
