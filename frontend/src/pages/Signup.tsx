import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Signup() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await register(email, password);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-up failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h2>Sign up</h2>
        <p className="muted">New accounts start with bonus credits.</p>
        <form onSubmit={submit}>
          <p><input className="input" type="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)} required /></p>
          <p><input className="input" type="password" placeholder="Password (min 8 chars)"
            value={password} onChange={(e) => setPassword(e.target.value)} required /></p>
          <button className="btn" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Creating…" : "Create account"}
          </button>
          {error && <div className="error">{error}</div>}
        </form>
        <p className="muted">Have an account? <Link to="/login">Log in</Link></p>
      </div>
    </div>
  );
}
