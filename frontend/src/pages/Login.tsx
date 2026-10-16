import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login } = useAuth();
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
      await login(email, password);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h2>Log in</h2>
        <form onSubmit={submit}>
          <p><input className="input" type="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)} required /></p>
          <p><input className="input" type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required /></p>
          <button className="btn" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Logging in…" : "Log in"}
          </button>
          {error && <div className="error">{error}</div>}
        </form>
        <p className="muted">No account? <Link to="/signup">Sign up</Link></p>
      </div>
    </div>
  );
}
