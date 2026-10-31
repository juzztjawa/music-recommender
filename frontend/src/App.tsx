import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";
import { Mark } from "./components/Icons";
import Chat from "./pages/Chat";
import Login from "./pages/Login";
import RunRedirect from "./pages/RunRedirect";
import Shell from "./pages/Shell";
import Verify from "./pages/Verify";

function RequireAuth({ children }: { children: ReactNode }) {
  const { email, loading } = useAuth();
  if (loading) return <p className="muted center-msg">Loading…</p>;
  return email ? <>{children}</> : <Navigate to="/login" replace />;
}

function AuthPage({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-brand">
        <Mark size={26} /> Orchestra
      </div>
      {children}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage><Login /></AuthPage>} />
      <Route path="/verify" element={<AuthPage><Verify /></AuthPage>} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Chat />} />
        <Route path="/t/:threadId" element={<Chat />} />
        <Route path="/runs/:runId" element={<RunRedirect />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
