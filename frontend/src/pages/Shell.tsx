import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { SidebarIcon } from "../components/Icons";
import Sidebar from "../components/Sidebar";
import type { ThreadSummary } from "../types";

export interface ShellContext {
  refreshThreads: () => void;
  toggleSidebar: () => void;
}

const COLLAPSE_KEY = "orchestra.sidebar.collapsed";

/** App frame: conversation list on the left, the routed chat on the right. */
export default function Shell() {
  const { email, logout } = useAuth();
  const location = useLocation();
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [drawer, setDrawer] = useState(false); // mobile
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  const refreshThreads = useCallback(() => {
    api
      .threads()
      .then((t) => {
        setThreads(t);
        setLoadError(false);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(refreshThreads, [refreshThreads]);
  useEffect(() => setDrawer(false), [location.pathname]);

  const toggleSidebar = useCallback(() => {
    if (window.matchMedia("(max-width: 800px)").matches) {
      setDrawer((d) => !d);
      return;
    }
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  }, []);

  const ctx: ShellContext = { refreshThreads, toggleSidebar };
  return (
    <div className={`shell ${collapsed ? "collapsed" : ""} ${drawer ? "drawer-open" : ""}`}>
      <Sidebar
        threads={threads}
        loadError={loadError}
        email={email ?? ""}
        onLogout={logout}
        onNavigate={() => setDrawer(false)}
      />
      <div className="backdrop" onClick={() => setDrawer(false)} />
      <div className="chat-col">
        <button className="icon-btn toggle" onClick={toggleSidebar} aria-label="Toggle sidebar">
          <SidebarIcon />
        </button>
        <Outlet context={ctx} />
      </div>
    </div>
  );
}
