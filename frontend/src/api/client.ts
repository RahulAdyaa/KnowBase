/* Typed API client with automatic access-token refresh.

   Tokens live in localStorage for the scaffold. Production hardening:
   httpOnly cookies + CSRF, short-lived access tokens, refresh rotation.
*/

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface User {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
}

export interface Citation {
  chunk_id: number;
  document_id: number;
  filename: string;
  score: number;
  snippet: string;
}

export interface DocumentInfo {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: "pending" | "processing" | "ready" | "failed";
  chunk_count: number;
  error: string;
  created_at: string;
}

export interface LedgerEntry {
  id: number;
  amount: number;
  balance_after: number;
  reason: string;
  created_at: string;
}

function getAccess(): string | null {
  return localStorage.getItem("rp_access");
}
function getRefresh(): string | null {
  return localStorage.getItem("rp_refresh");
}

export function saveTokens(t: TokenPair) {
  localStorage.setItem("rp_access", t.access_token);
  localStorage.setItem("rp_refresh", t.refresh_token);
}
export function clearTokens() {
  localStorage.removeItem("rp_access");
  localStorage.removeItem("rp_refresh");
}

async function refreshAccess(): Promise<boolean> {
  const rt = getRefresh();
  if (!rt) return false;
  const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) return false;
  const pair = (await res.json()) as TokenPair;
  saveTokens(pair);
  return true;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Authenticated JSON request. Retries once after refreshing an expired token. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
    };
    const token = getAccess();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (init.body && typeof init.body === "string" && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    return fetch(`${API_BASE}${path}`, { ...init, headers });
  };

  let res = await doFetch();
  if (res.status === 401 && getRefresh()) {
    if (await refreshAccess()) {
      res = await doFetch();
    }
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : msg;
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** POST an SSE chat request and stream events to callbacks. */
export async function streamChat(
  message: string,
  on: {
    citations: (c: Citation[]) => void;
    token: (t: string) => void;
    done: (info: { credits_charged: number; balance_after: number }) => void;
    error: (e: Error) => void;
  },
): Promise<void> {
  const token = getAccess();
  try {
    const res = await fetch(`${API_BASE}/api/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message }),
    });
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => "");
      throw new ApiError(res.status, text || `Chat failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let event = "";
    const dispatch = (data: string) => {
      try {
        const payload = JSON.parse(data);
        if (event === "citation") on.citations(payload.citations ?? []);
        else if (event === "token") on.token(payload.text ?? "");
        else if (event === "done") on.done(payload);
      } catch {
        /* ignore malformed chunks */
      }
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const lines = part.split("\n");
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (data) dispatch(data);
      }
    }
  } catch (e) {
    on.error(e instanceof Error ? e : new Error(String(e)));
  }
}
