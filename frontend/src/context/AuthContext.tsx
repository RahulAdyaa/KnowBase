import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch, clearTokens, saveTokens, type TokenPair, type User } from "../api/client";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore session on reload if tokens exist.
    if (!localStorage.getItem("rp_access")) {
      setLoading(false);
      return;
    }
    apiFetch<User>("/api/v1/auth/me")
      .then(setUser)
      .catch(() => clearTokens())
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const pair = await apiFetch<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    saveTokens(pair);
    setUser(await apiFetch<User>("/api/v1/auth/me"));
  };

  const register = async (email: string, password: string) => {
    const pair = await apiFetch<TokenPair>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    saveTokens(pair);
    setUser(await apiFetch<User>("/api/v1/auth/me"));
  };

  const logout = () => {
    clearTokens();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
