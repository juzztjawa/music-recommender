import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { email: signedIn } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (signedIn) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.requestLink(email.trim());
      setDevLink(res.dev_link ?? null);
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many requests — try again later."
          : "Couldn't send the link. Check the email address.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-card">
      <h1>Rediscover the feeling that made you love a song.</h1>
      {sent ? (
        devLink ? (
          <>
            <p className="muted">Test environment: no email is sent. Use the link below.</p>
            <a className="primary-link" href={devLink}>
              Open sign-in link
            </a>
          </>
        ) : (
          <p>
            If <strong>{email}</strong> is valid, a sign-in link is on its way. It works once and
            expires in 15 minutes.
          </p>
        )
      ) : (
        <form onSubmit={submit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
          <button className="primary" disabled={busy}>
            {busy ? "Sending…" : "Email me a sign-in link"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      )}
    </section>
  );
}
