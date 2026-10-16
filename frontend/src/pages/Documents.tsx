import { useEffect, useState } from "react";
import { apiFetch, ApiError, type DocumentInfo } from "../api/client";

export default function Documents() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  const load = () =>
    apiFetch<{ documents: DocumentInfo[] }>("/api/v1/documents")
      .then((r) => setDocs(r.documents))
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed"));

  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // poll ingestion status
    return () => clearInterval(t);
  }, []);

  const upload = async (file: File) => {
    setError("");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const token = localStorage.getItem("rp_access");
      const res = await fetch("/api/v1/documents/upload", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, (body as { detail?: string }).detail ?? "Upload failed");
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this document and its embeddings?")) return;
    await apiFetch(`/api/v1/documents/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div>
      <h2>Documents</h2>
      <div className="card">
        <label className="row">
          <input
            type="file"
            accept=".txt,.md,.markdown,.csv,.json"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
              e.target.value = "";
            }}
          />
          {uploading && <span className="muted">Uploading…</span>}
        </label>
        <p className="muted">Supported: .txt, .md, .csv, .json (PDF parsing is a planned extension).</p>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="card">
        <table className="table">
          <thead>
            <tr><th>File</th><th>Status</th><th>Chunks</th><th></th></tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>{d.filename}</td>
                <td>{d.status}{d.error ? ` — ${d.error}` : ""}</td>
                <td>{d.chunk_count}</td>
                <td><button className="btn btn-ghost" onClick={() => remove(d.id)}>Delete</button></td>
              </tr>
            ))}
            {docs.length === 0 && <tr><td colSpan={4} className="muted">No documents yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
