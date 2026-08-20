"use client";

import { useState, useRef, useEffect } from "react";

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setEvents([]);
    setResult(null);
    setError("");

    try {
      const formData = new URLSearchParams();
      formData.append("query", query);

      const res = await fetch("http://127.0.0.1:8000/", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: formData.toString(),
      });

      if (!res.ok) {
        throw new Error("Failed to start agent.");
      }

      const data = await res.json();
      if (data.job_id) {
        startSSE(data.job_id);
      }
    } catch (err: any) {
      setError(err.message || "An error occurred");
      setLoading(false);
    }
  };

  const startSSE = (jobId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const sse = new EventSource(`http://127.0.0.1:8000/stream/${jobId}`);
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
            if (prev.find((ev) => ev.step === data.step && ev.detail === data.detail)) {
              return prev;
            }
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
  };

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

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
            placeholder="Enter a company or role"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
          />
          <button type="submit" className="btn-investigate" disabled={loading}>
            {loading ? 'Investigating...' : 'Investigate →'}
          </button>
        </form>
      </div>

      {error && (
        <div style={{ color: 'var(--error)', marginBottom: '2rem', padding: '1rem', border: '1px solid var(--error)', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(239, 68, 68, 0.1)' }}>
          {error}
        </div>
      )}

      {/* Results / Live Investigation Area */}
      <div style={{ animation: 'fadeIn 0.5s ease-out' }}>
        
        {/* Company Dossier (Card 1) */}
        <div className="card-light">
            <div className="card-header card-header-light">
              <span>COMPANY DOSSIER</span>
              <span style={{ color: 'var(--text-muted)' }}>ID: {result ? '4470' : 'SCANNING...'}</span>
            </div>
            
            <h2 className="card-title">
            {result ? result.company_name?.replace(' ', ' / ') || 'Unknown' : query || 'Pattern / Labs'}
          </h2>
            <p className="card-subtitle">
              {result?.rationale || 'Extracting workflow intelligence...'}
            </p>
            
            <div className="stats-row">
              <div className="stat-item">
                <span className="stat-value">{result ? 'Series B' : '--'}</span>
                <span className="stat-label">STAGE</span>
              </div>
              <div className="stat-item">
                <span className="stat-value">{result ? '18' : '--'}</span>
                <span className="stat-label">OPEN ROLES</span>
              </div>
            </div>
          </div>

          {/* Active Signal Path (Card 2) */}
          <div className="card-dark">
            <div className="card-header card-header-dark" style={{ justifyContent: 'space-between', display: 'flex' }}>
              <span>ACTIVE SIGNAL PATH</span>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent-blue)' }}>
                <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
              </svg>
            </div>
            
            <h3 className="card-title-dark">
              {result 
                ? (result.news_signals && result.news_signals.length > 0 
                    ? result.news_signals[0].title 
                    : "New infrastructure roles point to a scaling moment in their product org.") 
                : "Analyzing market events..."}
            </h3>
            
            <div className="card-dark-inner">
              <span className="dark-label">MARKET EVENT → TEAM EXPANSION</span>
              <p className="dark-text">
                {result 
                  ? "Your systems-design experience gives you a credible entry point."
                  : "Gathering evidence trail..."}
              </p>
            </div>
          </div>

          {/* Steps Row */}
          <div className="steps-grid">
            <div className="step-col">
              <div className="step-number">02.1</div>
              <div className="step-desc">Found a public hiring signal for design systems leadership.</div>
            </div>
            <div className="step-col">
              <div className="step-number">02.2</div>
              <div className="step-desc">Their product launch creates a timely route into the design team.</div>
            </div>
            <div className="step-col">
              <div className="step-number">02.3</div>
              <div className="step-desc">Outly can draft an evidence-led opening note in under one minute.</div>
            </div>
        </div>
      </div>
    </div>
  );
}
