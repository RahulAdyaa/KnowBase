import { useEffect, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { apiFetch } from "./api/client";
import ProtectedRoute from "./components/ProtectedRoute";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Chat from "./pages/Chat";
import Documents from "./pages/Documents";
import Billing from "./pages/Billing";

function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [balance, setBalance] = useState<number | null>(null);

  useEffect(() => {
    if (!user) return;
    apiFetch<{ balance: number }>("/api/v1/credits/balance")
      .then((b) => setBalance(b.balance))
      .catch(() => setBalance(null));
  }, [user]);

  const onLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>RAG Platform</h1>
        <NavLink to="/chat">Chat</NavLink>
        <NavLink to="/documents">Documents</NavLink>
        <NavLink to="/billing">Billing</NavLink>
        {user?.role === "admin" && <span className="muted" style={{ padding: "10px 12px" }}>admin: {user.email}</span>}
        <div style={{ marginTop: "auto", padding: 8 }}>
          <div className="balance-pill" style={{ margin: 0 }}>
            {balance === null ? "…" : `${balance} credits`}
          </div>
          <button className="btn btn-ghost" style={{ width: "100%", marginTop: 8 }} onClick={onLogout}>
            Log out
          </button>
        </div>
      </nav>
      <div className="main">
        <Routes>
          <Route path="/chat" element={<Chat onBalance={setBalance} />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/billing" element={<Billing onBalance={setBalance} />} />
          <Route path="*" element={<Chat onBalance={setBalance} />} />
        </Routes>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/*" element={<Shell />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
