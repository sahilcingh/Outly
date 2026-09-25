"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "../../config";
import { Reveal, PopIn, AnimatePresence, fadeUp, staggerContainer, motion } from "../../motion-primitives";
import { Spinner } from "@/components/ui/spinner";
import { CopyButton } from "@/components/ui/copy-button";

type ApiKey = {
  id: number;
  name: string;
  preview: string;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
};

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyName, setKeyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [error, setError] = useState("");

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/api-keys`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) setKeys(data.keys || []);
    } catch (err) {
      console.error("Failed to fetch API keys", err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyName.trim()) return;
    setCreating(true);
    setError("");
    setNewKey("");
    try {
      const body = new URLSearchParams({ key_name: keyName.trim() });
      const res = await fetch(`${API_BASE_URL}/api/v1/api-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
        credentials: "include",
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || "Failed to create key.");
      setNewKey(data.key);
      setKeys(data.keys || []);
      setKeyName("");
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: number) => {
    if (!confirm("Revoke this key? Any apps using it will stop working.")) return;
    try {
      await fetch(`${API_BASE_URL}/api/v1/api-keys/${id}/revoke`, { method: "POST", credentials: "include" });
      fetchKeys();
    } catch (err) {
      console.error("Failed to revoke key", err);
    }
  };

  return (
    <div>
      <Reveal className="flex justify-between items-center mb-6" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h1 className="text-hero" style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>API Keys</h1>
          <p className="text-subhero">Use API keys to access Outly programmatically from your own tools, CRM, or ATS.</p>
        </div>
        <a href="/api-docs" className="text-sm text-[var(--accent-blue)] hover:underline">📖 API Docs</a>
      </Reveal>

      <AnimatePresence>
      {newKey && (
        <PopIn className="card-light" style={{ borderColor: "var(--success)", marginBottom: "1.5rem" }}>
          <h3 className="text-h3" style={{ color: "var(--success)" }}>✅ API Key Created. Copy it now!</h3>
          <p className="text-sm text-muted" style={{ margin: "0.25rem 0 0.75rem" }}>This key will never be shown again.</p>
          <div className="text-sm" style={{ fontFamily: "monospace", backgroundColor: "var(--bg-main)", border: "1px solid var(--border-color)", borderRadius: "var(--radius-sm)", padding: "0.65rem", wordBreak: "break-all" }}>
            {newKey}
          </div>
          <div className="flex items-center gap-1 mt-2" style={{ marginTop: "0.5rem", border: "1px solid var(--text-primary)", borderRadius: "var(--radius-sm)", padding: "0 0.25rem 0 1rem", height: "2.4rem", width: "fit-content" }}>
            <span className="text-sm font-medium">Copy Key</span>
            <CopyButton code={newKey} className="!bg-transparent !border-0 !text-[var(--text-primary)] hover:!bg-[var(--border-color)] hover:!text-[var(--text-primary)]" />
          </div>
          <p className="text-xs" style={{ color: "var(--error)", marginTop: "0.5rem" }}>⚠️ Store this key securely. Treat it like a password.</p>
        </PopIn>
      )}
      </AnimatePresence>

      <motion.form
        initial="hidden" animate="show" variants={fadeUp} transition={{ delay: 0.05 }}
        onSubmit={handleCreate} className="card-light flex gap-3 items-end" style={{ flexWrap: "wrap" }}
      >
        <div className="flex flex-col gap-2" style={{ flex: "1 1 260px" }}>
          <label className="text-sm font-medium">Key Name (to identify it later)</label>
          <input
            type="text" className="input" placeholder="e.g. My CRM Integration"
            value={keyName} onChange={(e) => setKeyName(e.target.value)} disabled={creating} required
          />
        </div>
        <button type="submit" className="btn btn-primary" disabled={creating}>
          {creating ? "Generating..." : "+ Generate Key"}
        </button>
      </motion.form>

      <AnimatePresence>
      {error && (
        <PopIn className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)", marginTop: "1rem" }}>
          {error}
        </PopIn>
      )}
      </AnimatePresence>

      <Reveal delay={0.1} className="card-light" style={{ marginTop: "1.5rem" }}>
        <h2 className="text-h3 mb-4" style={{ marginBottom: "1rem" }}>Your API Keys</h2>

        {loading ? (
          <div className="flex justify-center" style={{ padding: "2rem" }}>
            <Spinner className="size-6 text-[var(--accent-blue)]" />
          </div>
        ) : keys.length === 0 ? (
          <div className="text-muted text-sm" style={{ textAlign: "center", padding: "2rem" }}>No API keys yet. Generate one above to get started.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr>
                  {["Name", "Key Preview", "Status", "Created", "Last Used", ""].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "0.6rem 0.75rem", borderBottom: "2px solid var(--border-color)", color: "var(--text-muted)", fontSize: "0.75rem", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <motion.tbody initial="hidden" animate="show" variants={staggerContainer}>
                {keys.map((key) => (
                  <motion.tr key={key.id} variants={fadeUp}>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)", fontWeight: 600 }}>{key.name}</td>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)", fontFamily: "monospace", color: "var(--text-muted)" }}>{key.preview}</td>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)" }}>
                      <span className={`badge ${key.is_active ? "badge-success" : "badge-error"}`}>{key.is_active ? "Active" : "Revoked"}</span>
                    </td>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)" }}>{key.created_at?.slice(0, 10)}</td>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)" }}>{key.last_used_at ? key.last_used_at.slice(0, 10) : "Never"}</td>
                    <td style={{ padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--border-color)" }}>
                      {key.is_active && (
                        <button onClick={() => handleRevoke(key.id)} className="btn btn-secondary text-xs px-3 py-1" style={{ color: "var(--error)", borderColor: "var(--error)" }}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </motion.tr>
                ))}
              </motion.tbody>
            </table>
          </div>
        )}
      </Reveal>
    </div>
  );
}
