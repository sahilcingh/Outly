"use client";

import { useState, useRef, useEffect } from "react";
import { API_BASE_URL } from "./config";

type EventItem = {
  step: string;
  label: string;
  detail: string;
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q) {
      setQuery(q);
      handleSearch(q);
    }
  }, []);

  const handleSearch = async (searchQuery: string) => {
    if (!searchQuery.trim()) return;

    setLoading(true);
    setEvents([]);
    setResult(null);
    setError("");

    try {
      const formData = new URLSearchParams();
      formData.append("query", searchQuery);

      const res = await fetch(`${API_BASE_URL}/`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString(),
        credentials: "include", // For session fallback
      });

      if (!res.ok) throw new Error(`Failed to start agent: ${res.statusText}`);

      const data = await res.json();
      if (data.error) throw new Error(data.error);
      const jobId = data.job_id;

      // Connect to SSE stream
      const sse = new EventSource(`${API_BASE_URL}/stream/${jobId}`);
      eventSourceRef.current = sse;

      sse.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.step === "__result__") {
            setResult(data.result);
            setLoading(false);
            sse.close();
          } else if (data.step === "error") {
            setError(data.label || "Pipeline error");
            setLoading(false);
            sse.close();
          } else {
            setEvents((prev) => {
              if (prev.find((ev) => ev.step === data.step && ev.detail === data.detail)) return prev;
              return [...prev, data];
            });
          }
        } catch (err) {
          console.error("SSE Parse error", err);
        }
      };

      sse.onerror = () => {
        setError("Lost connection to the server.");
        setLoading(false);
        sse.close();
      };
    } catch (err: any) {
      setError(err.message || "An error occurred");
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSearch(query);
  };

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  const hiringSignals: {title: string, url: string}[] = result?.hiring_signals ?? [];
  const newsSignals: {title: string}[] = result?.news_signals ?? [];
  const openRolesCount = hiringSignals.length;
  const companyName = result?.company_name ?? query ?? "Pattern / Labs";
  const rationale = result?.rationale ?? "Extracting workflow intelligence...";
  const contactTitle = result?.contact_title;
  const contactName = result?.contact_name;
  const roleToOffer = result?.role_to_offer;

  return (
    <div>
      {/* Hero Section & Search */}
      <div className="mb-4">
        <span className="text-overline">01 / RESEARCH TARGET</span>
        <h1 className="text-hero">
          Turn company noise into an unfair<br/>advantage.
        </h1>
      </div>

      <div className="flex justify-between items-center mb-12 flex-wrap gap-6">
        <p className="text-subhero" style={{ margin: 0 }}>
          Point Outly at a company and follow the evidence trail—signals,<br/>
          hiring intent, and the exact angle for your first conversation.
        </p>

        <form className="search-container" onSubmit={handleSubmit}>
          <svg className="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            type="text"
            className="search-input"
            placeholder="Enter a company name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
          />
          <button type="submit" className="btn-investigate" disabled={loading}>
            {loading ? "Investigating..." : "Investigate →"}
          </button>
        </form>
      </div>

      {/* Live Progress Events */}
      {loading && events.length > 0 && (
        <div style={{ marginBottom: "1.5rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          {events.map((ev, i) => (
            <div key={i} style={{ fontSize: "0.8rem", color: "var(--text-muted)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <span>{ev.label}</span>
              {ev.detail && <span style={{ opacity: 0.6 }}>— {ev.detail}</span>}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div style={{ color: "var(--error)", marginBottom: "2rem", padding: "1rem", border: "1px solid var(--error)", borderRadius: "var(--radius-md)", backgroundColor: "rgba(239, 68, 68, 0.1)" }}>
          {error}
        </div>
      )}

      {/* Results */}
      <div style={{ animation: "fadeIn 0.5s ease-out" }}>

        {/* Company Dossier */}
        <div className="card-light">
          <div className="card-header card-header-light">
            <span>COMPANY DOSSIER</span>
            <span style={{ color: "var(--text-muted)" }}>
              {result ? companyName.toUpperCase() : "SCANNING..."}
            </span>
          </div>

          <h2 className="card-title">{companyName}</h2>
          <p className="card-subtitle">{rationale}</p>

          <div className="stats-row">
            <div className="stat-item">
              <span className="stat-value">{result ? openRolesCount : "--"}</span>
              <span className="stat-label">OPEN ROLES FOUND</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ fontSize: "0.95rem" }}>
                {result ? (contactTitle ?? "N/A") : "--"}
              </span>
              <span className="stat-label">TARGET CONTACT</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ fontSize: "0.95rem" }}>
                {result ? (roleToOffer ?? "N/A") : "--"}
              </span>
              <span className="stat-label">ROLE TO OFFER</span>
            </div>
          </div>

          {/* Role pills (clickable) */}
          {result && hiringSignals.length > 0 && (
            <div style={{ marginTop: "1.25rem", borderTop: "1px solid var(--border-color)", paddingTop: "1rem" }}>
              <span style={{ fontSize: "0.7rem", letterSpacing: "0.1em", color: "var(--text-muted)", fontWeight: 600 }}>
                OPEN ROLES DETECTED
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.5rem" }}>
                {hiringSignals.map((role, i) => (
                  <a
                    key={i}
                    href={role.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: "0.75rem",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      border: "1px solid var(--border-color)",
                      color: "var(--accent-blue)",
                      backgroundColor: "var(--bg-main)",
                      textDecoration: "none",
                    }}
                  >
                    {role.title} ↗
                  </a>
                ))}
              </div>
            </div>
          )}

          {result && hiringSignals.length === 0 && (
            <div style={{ marginTop: "1rem", fontSize: "0.8rem", color: "var(--text-muted)", borderTop: "1px solid var(--border-color)", paddingTop: "0.75rem" }}>
              No open tech roles found on their careers page or ATS platforms.
            </div>
          )}
        </div>

        {/* Active Signal Path */}
        <div className="card-dark">
          <div className="card-header card-header-dark" style={{ justifyContent: "space-between", display: "flex" }}>
            <span>ACTIVE SIGNAL PATH</span>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--accent-blue)" }}>
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
            </svg>
          </div>

          <h3 className="card-title-dark">
            {result
              ? (newsSignals.length > 0
                  ? newsSignals[0].title
                  : (openRolesCount > 0
                      ? `${openRolesCount} open role${openRolesCount > 1 ? "s" : ""} signal active hiring at ${companyName}.`
                      : "No recent public hiring signals detected."))
              : "Analyzing market events..."}
          </h3>

          <div className="card-dark-inner">
            <span className="dark-label">
              {result
                ? (openRolesCount > 0 ? "HIRING SIGNAL → TEAM EXPANSION" : "LOW SIGNAL ENVIRONMENT")
                : "MARKET EVENT → TEAM EXPANSION"}
            </span>
            <p className="dark-text" style={{ whiteSpace: "pre-wrap" }}>
              {result
                ? (result.subject ? `Outly identified "${roleToOffer || "N/A"}" as the optimal role to offer — targeting ${contactName || "N/A"} (${contactTitle || "N/A"}).` : "Gathering evidence...")
                : "Gathering evidence trail..."}
            </p>
          </div>
        </div>

      </div>
    </div>
  );
}
