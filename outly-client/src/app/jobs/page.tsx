"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { API_BASE_URL } from "../config";

type EventItem = { step: string; label: string; detail: string };

type JobApplication = {
  id: number;
  job_title: string;
  company_name: string;
  company_url: string | null;
  job_url: string;
  ats_url: string | null;
  location: string;
  is_remote: boolean;
  source: string;
  apply_method: string;
  match_score: number;
  match_rationale: string;
  key_matches: string; // JSON-encoded list
  gaps: string; // JSON-encoded list
  status: string;
  date_posted: string;
  created_at: string;
};

const STEP_LABELS: Record<string, string> = {
  extracting: "🔍 Reading your resume...",
  profile_ready: "✅ Profile extracted",
  searching: "🔎 Searching job boards...",
  scoring: "📊 Scoring matches...",
  generating: "✍️ Writing cover letters...",
  done: "🎉 Done",
};

function scoreClass(score: number) {
  if (score >= 70) return "badge-success";
  if (score >= 40) return "badge-warning";
  return "badge-error";
}

function parseListField(raw: string): string[] {
  try {
    const v = JSON.parse(raw || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export default function JobsPage() {
  // --- search form state ---
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumeText, setResumeText] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [keywords, setKeywords] = useState("");
  const [location, setLocation] = useState("Remote");
  const [minScore, setMinScore] = useState(60);
  const [remoteOnly, setRemoteOnly] = useState(false);

  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [resultBanner, setResultBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [error, setError] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

  // --- queue state ---
  const [jobs, setJobs] = useState<JobApplication[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  const fetchQueue = async (status: string) => {
    setQueueLoading(true);
    try {
      const qs = status === "all" ? "" : `?status=${status}`;
      const res = await fetch(`${API_BASE_URL}/api/v1/jobs/queue${qs}`);
      if (res.ok) {
        const data = await res.json();
        setJobs(data.jobs || []);
      }
    } catch (err) {
      console.error("Failed to fetch job queue", err);
    }
    setQueueLoading(false);
  };

  useEffect(() => {
    fetchQueue(filter);
  }, [filter]);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  const startSSE = (jobId: string) => {
    const sse = new EventSource(`${API_BASE_URL}/stream/${jobId}`);
    eventSourceRef.current = sse;

    sse.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.step === "__result__") {
          const saved = data.result?.saved;
          setLoading(false);
          if (typeof saved === "number" && saved > 0) {
            setResultBanner({ type: "success", text: `Done! ${saved} jobs added to your review queue.` });
            fetchQueue(filter);
          } else if (typeof saved === "number") {
            setResultBanner({ type: "success", text: "No new jobs to add — everything found is already in your queue." });
          } else {
            setResultBanner({ type: "error", text: data.error || "Something went wrong." });
          }
          sse.close();
        } else if (data.step === "error") {
          setLoading(false);
          setResultBanner({ type: "error", text: data.detail || data.label || "Job search failed." });
          sse.close();
        } else {
          setEvents((prev) => {
            if (prev.find((ev) => ev.step === data.step && ev.detail === data.detail)) return prev;
            return [...prev, { step: data.step, label: STEP_LABELS[data.step] || data.label, detail: data.detail }];
          });
        }
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };

    sse.onerror = () => {
      setLoading(false);
      setResultBanner({ type: "error", text: "Connection lost. Refresh to check results." });
      sse.close();
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resumeFile && !resumeText.trim()) {
      setError("Please upload a PDF resume or paste your resume text.");
      return;
    }

    setLoading(true);
    setError("");
    setResultBanner(null);
    setEvents([]);

    try {
      const formData = new FormData();
      if (resumeFile) formData.append("resume_file", resumeFile);
      formData.append("resume_text", resumeText);
      formData.append("candidate_name", candidateName);
      formData.append("keywords", keywords);
      formData.append("location", location || "Remote");
      formData.append("min_score", String(minScore));
      formData.append("remote_only", remoteOnly ? "true" : "false");

      // The backend redirects (303) to /jobs?job_id=... on success. Same-origin
      // via the proxy, so fetch follows it and res.url carries the final job_id.
      const res = await fetch(`${API_BASE_URL}/jobs`, { method: "POST", body: formData });
      if (!res.ok) throw new Error("Failed to start job search.");

      const jobId = new URL(res.url).searchParams.get("job_id");
      if (!jobId) {
        // No job_id means the backend re-rendered the form with a validation error.
        throw new Error("Please upload a PDF resume or paste your resume text.");
      }
      startSSE(jobId);
    } catch (err: any) {
      setLoading(false);
      setError(err.message || "An error occurred");
    }
  };

  const jobAction = async (id: number, action: "approve" | "reject" | "applied") => {
    try {
      await fetch(`${API_BASE_URL}/jobs/${id}/${action}`, { method: "POST" });
      fetchQueue(filter);
    } catch (err) {
      console.error("Job action failed", err);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <h1 className="text-hero" style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>Automated Job Search</h1>
        <p className="text-subhero">Upload your resume — Outly searches LinkedIn &amp; Indeed, scores matches, and writes tailored cover letters.</p>
      </div>

      <div className="flex gap-6 flex-wrap lg:flex-nowrap items-start">
        <div className="w-full" style={{ maxWidth: "500px" }}>
          <form className="card-light flex flex-col gap-4" onSubmit={handleSubmit} style={{ padding: "2rem" }}>
            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium">Your Resume</label>
              <label
                className="upload-area"
                style={{
                  border: "2px dashed var(--border-color)", borderRadius: "8px", padding: "1rem",
                  textAlign: "center", cursor: "pointer", fontSize: "0.85rem", color: "var(--text-muted)",
                }}
              >
                <input
                  type="file"
                  accept=".pdf,.txt,.doc,.docx"
                  style={{ display: "none" }}
                  disabled={loading}
                  onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                />
                {resumeFile ? resumeFile.name : "Click to upload a PDF resume"}
              </label>
              <div className="text-xs text-muted text-center">— or paste your resume below —</div>
              <textarea
                className="input"
                placeholder="Paste your resume text here..."
                rows={5}
                value={resumeText}
                onChange={(e) => setResumeText(e.target.value)}
                disabled={loading}
                style={{ resize: "none" }}
              />
            </div>

            <div className="flex gap-4 flex-wrap">
              <div className="flex flex-col gap-2" style={{ flex: "1 1 180px" }}>
                <label className="text-sm font-medium">Your Name</label>
                <input
                  type="text" className="input" placeholder="Jane Doe"
                  value={candidateName} onChange={(e) => setCandidateName(e.target.value)} disabled={loading}
                />
              </div>
              <div className="flex flex-col gap-2" style={{ flex: "1 1 180px" }}>
                <label className="text-sm font-medium">Keywords <span className="text-xs text-muted">(optional)</span></label>
                <input
                  type="text" className="input" placeholder="e.g. Python backend engineer"
                  value={keywords} onChange={(e) => setKeywords(e.target.value)} disabled={loading}
                />
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium">Location</label>
              <input
                type="text" className="input" placeholder="Remote, New York, etc."
                value={location} onChange={(e) => setLocation(e.target.value)} disabled={loading}
              />
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium">
                Min Match Score: <span style={{ color: "var(--accent-blue)", fontWeight: 700 }}>{minScore}</span>
              </label>
              <input
                type="range" min={0} max={100} value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                disabled={loading}
              />
              <div className="text-xs text-muted">Jobs below this score are still saved, just without a cover letter.</div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} disabled={loading} />
              Remote-only positions
            </label>

            <button type="submit" className={`btn btn-primary w-full ${loading ? "pulse" : ""}`} disabled={loading}>
              {loading ? "Searching..." : "Find Jobs"}
            </button>

            {error && (
              <div className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }}>
                {error}
              </div>
            )}

            {loading && events.length > 0 && (
              <div className="flex flex-col gap-1" style={{ marginTop: "0.5rem" }}>
                {events.map((ev, i) => (
                  <div key={i} className="text-xs text-muted flex gap-2">
                    <span>{ev.label}</span>
                    {ev.detail && <span style={{ opacity: 0.7 }}>— {ev.detail}</span>}
                  </div>
                ))}
              </div>
            )}

            {resultBanner && (
              <div
                className="p-3 rounded-md text-sm"
                style={
                  resultBanner.type === "success"
                    ? { backgroundColor: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", color: "var(--success)" }
                    : { backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }
                }
              >
                {resultBanner.text}
              </div>
            )}
          </form>
        </div>

        <div className="flex-1 w-full">
          <div className="card-light flex flex-col gap-4" style={{ minHeight: "400px" }}>
            <div className="flex justify-between items-center flex-wrap gap-2 border-b border-[var(--border-color)] pb-4">
              <h2 className="text-h3">Job Queue</h2>
              <div className="flex gap-2 flex-wrap">
                {["all", "queued", "approved", "applied", "rejected"].map((s) => (
                  <button
                    key={s}
                    onClick={() => setFilter(s)}
                    className={`btn ${filter === s ? "btn-primary" : "btn-secondary"} text-xs px-3 py-1`}
                    style={{ textTransform: "capitalize" }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {queueLoading ? (
              <div className="flex justify-center" style={{ minHeight: "200px", alignItems: "center" }}>
                <div className="pulse" style={{ width: "20px", height: "20px", borderRadius: "50%", backgroundColor: "var(--accent-blue)" }}></div>
              </div>
            ) : jobs.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center opacity-50" style={{ minHeight: "200px" }}>
                <h3 className="text-h3 mb-2">No Jobs Found</h3>
                <p className="text-muted max-w-[250px]">
                  {filter === "all" ? "Start a search to find jobs tailored to your resume." : `No jobs with status "${filter}".`}
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {jobs.map((job) => {
                  const matches = parseListField(job.key_matches).slice(0, 3);
                  const gaps = parseListField(job.gaps).slice(0, 2);
                  return (
                    <div key={job.id} className="flex flex-col gap-2 p-4 rounded-md" style={{ border: "1px solid var(--border-color)" }}>
                      <div className="flex justify-between items-start gap-3">
                        <div>
                          <div className="text-sm font-medium">{job.job_title}</div>
                          <div className="text-xs text-muted">{job.company_name}</div>
                        </div>
                        <span className={`badge ${scoreClass(job.match_score)}`} style={{ flexShrink: 0 }}>
                          {job.match_score}%
                        </span>
                      </div>

                      <div className="flex gap-2 flex-wrap items-center text-xs">
                        {job.location && <span className="text-muted">{job.location}</span>}
                        {job.is_remote && <span className="badge badge-success">Remote</span>}
                        <span className="badge badge-neutral">{job.source}</span>
                        <span className="badge badge-neutral">{job.apply_method.replace("ats_", "")}</span>
                        <span className="badge badge-warning" style={{ textTransform: "capitalize" }}>{job.status}</span>
                      </div>

                      {job.match_rationale && (
                        <div className="text-xs" style={{ color: "var(--text-secondary)", borderLeft: "2px solid var(--border-color)", paddingLeft: "0.5rem" }}>
                          {job.match_rationale}
                        </div>
                      )}
                      {matches.length > 0 && (
                        <div className="text-xs"><strong style={{ color: "var(--success)" }}>Matches:</strong> {matches.join(" · ")}</div>
                      )}
                      {gaps.length > 0 && (
                        <div className="text-xs text-muted"><strong style={{ color: "var(--error)" }}>Gaps:</strong> {gaps.join(" · ")}</div>
                      )}

                      <div className="flex gap-2 flex-wrap pt-2" style={{ borderTop: "1px solid var(--border-color)" }}>
                        <Link href={`/jobs/${job.id}`} className="btn btn-secondary text-xs px-3 py-1">View &amp; Edit</Link>
                        {job.status === "queued" && (
                          <>
                            <button onClick={() => jobAction(job.id, "approve")} className="btn btn-secondary text-xs px-3 py-1" style={{ color: "var(--success)", borderColor: "var(--success)" }}>Approve</button>
                            <button onClick={() => jobAction(job.id, "reject")} className="btn btn-secondary text-xs px-3 py-1" style={{ color: "var(--error)", borderColor: "var(--error)" }}>Reject</button>
                          </>
                        )}
                        {job.status === "approved" && (
                          <>
                            <a href={job.ats_url || job.job_url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary text-xs px-3 py-1">Open Job ↗</a>
                            <button onClick={() => jobAction(job.id, "applied")} className="btn btn-primary text-xs px-3 py-1">Mark Applied</button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
