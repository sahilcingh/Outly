"use client";

import { useState } from "react";
import { API_BASE_URL } from "../config";
import { Reveal, PopIn, AnimatePresence, fadeUp, motion } from "../motion-primitives";

export default function BatchPage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Please choose a CSV file.");
      return;
    }

    setLoading(true);
    setError("");
    setMessage("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_BASE_URL}/api/v1/batch`, {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || "Batch upload failed.");

      setMessage(`Processed ${data.processed} companies. Check the Drafts page for results.`);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Reveal className="mb-6">
        <h1 className="text-hero" style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>Batch Upload</h1>
        <p className="text-subhero">Upload a CSV file to prospect multiple companies at once. Each row runs the full pipeline.</p>
      </Reveal>

      <motion.form
        initial="hidden" animate="show" variants={fadeUp} transition={{ delay: 0.1 }}
        className="card-light flex flex-col gap-4" onSubmit={handleSubmit} style={{ maxWidth: "560px" }}
      >
        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium">CSV File</label>
          <label
            className="upload-area"
            style={{
              border: "2px dashed var(--border-color)", borderRadius: "8px", padding: "1rem",
              textAlign: "center", cursor: "pointer", fontSize: "0.85rem", color: "var(--text-muted)",
            }}
          >
            <input
              type="file"
              accept=".csv"
              style={{ display: "none" }}
              disabled={loading}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? file.name : "Click to upload a CSV file"}
          </label>
          <div className="text-xs text-muted">
            Required column: <code>company_name</code> &nbsp; Optional: <code>industry</code>, <code>job_title</code>
          </div>
        </div>

        <button type="submit" className={`btn btn-primary w-full ${loading ? "pulse" : ""}`} disabled={loading}>
          {loading ? "Processing companies. This may take a few minutes..." : "Run Batch"}
        </button>

        <AnimatePresence>
        {message && (
          <PopIn className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", color: "var(--success)" }}>
            {message} <a href="/drafts" className="text-[var(--accent-blue)] hover:underline">View all drafts →</a>
          </PopIn>
        )}

        {error && (
          <PopIn className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }}>
            <strong>Error:</strong> {error}
          </PopIn>
        )}
        </AnimatePresence>

        <details>
          <summary className="text-sm text-muted" style={{ cursor: "pointer" }}>Example CSV format</summary>
          <pre className="text-xs mt-2" style={{ backgroundColor: "var(--bg-main)", padding: "0.75rem", borderRadius: "var(--radius-sm)", overflowX: "auto" }}>
{`company_name,industry,job_title
Acme Corp,Healthcare SaaS,CTO
Globex Corp,,
Initech,FinTech,VP of Engineering`}
          </pre>
        </details>
      </motion.form>
    </div>
  );
}
