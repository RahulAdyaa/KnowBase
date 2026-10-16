import { useEffect, useState } from "react";
import { apiFetch, type LedgerEntry } from "../api/client";

export default function Billing({ onBalance }: { onBalance: (b: number) => void }) {
  const [balance, setBalance] = useState<number | null>(null);
  const [history, setHistory] = useState<LedgerEntry[]>([]);
  const [amount, setAmount] = useState(100);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const b = await apiFetch<{ balance: number }>("/api/v1/credits/balance");
    setBalance(b.balance);
    onBalance(b.balance);
    const h = await apiFetch<{ entries: LedgerEntry[] }>("/api/v1/credits/history?limit=50");
    setHistory(h.entries);
  };

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : "Load failed"));
  }, []);

  const topup = async () => {
    setError("");
    setBusy(true);
    try {
      const b = await apiFetch<{ balance: number }>("/api/v1/credits/topup", {
        method: "POST",
        body: JSON.stringify({ credits: amount }),
      });
      setBalance(b.balance);
      onBalance(b.balance);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Top-up failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2>Billing</h2>
      <div className="card row">
        <div>
          <div className="muted">Current balance</div>
          <div style={{ fontSize: 32, fontWeight: 700 }}>
            {balance === null ? "…" : `${balance} credits`}
          </div>
        </div>
      </div>
      <div className="card">
        <h3>Top up</h3>
        <p className="muted">
          Demo mode credits instantly. Production uses Stripe Checkout + webhook.
        </p>
        <div className="row">
          <input
            className="input" style={{ maxWidth: 160 }} type="number" min={1} max={100000}
            value={amount} onChange={(e) => setAmount(Number(e.target.value))}
          />
          <button className="btn" onClick={topup} disabled={busy}>
            {busy ? "…" : `Add ${amount} credits`}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
      <div className="card">
        <h3>Usage history</h3>
        <table className="table">
          <thead><tr><th>When</th><th>Reason</th><th>Amount</th><th>Balance after</th></tr></thead>
          <tbody>
            {history.map((e) => (
              <tr key={e.id}>
                <td className="muted">{new Date(e.created_at).toLocaleString()}</td>
                <td>{e.reason}</td>
                <td style={{ color: e.amount < 0 ? "var(--danger)" : "inherit" }}>
                  {e.amount > 0 ? `+${e.amount}` : e.amount}
                </td>
                <td>{e.balance_after}</td>
              </tr>
            ))}
            {history.length === 0 && <tr><td colSpan={4} className="muted">No transactions yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
