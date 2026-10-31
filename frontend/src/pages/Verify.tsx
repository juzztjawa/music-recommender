import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Verify() {
  const [params] = useSearchParams();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);
  // Tokens are single-use and StrictMode runs effects twice in dev.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = params.get("token");
    if (!token) {
      setFailed(true);
      return;
    }
    api
      .verify(token)
      .then(login)
      .then(() => navigate("/", { replace: true }))
      .catch(() => setFailed(true));
  }, [params, login, navigate]);

  return (
    <section className="auth-card">
      {failed ? (
        <>
          <p className="error">This link is invalid or has expired.</p>
          <Link to="/login">Request a new one</Link>
        </>
      ) : (
        <p className="muted">Signing you in…</p>
      )}
    </section>
  );
}
