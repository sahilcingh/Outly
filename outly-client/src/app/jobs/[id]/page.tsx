"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { API_BASE_URL } from "../../config";

type Job = {
  id: number;
  job_title: string;
  company_name: string;
  company_url: string | null;
  job_url: string;
  ats_url: string | null;
  contact_email: string | null;
  location: string;
  is_remote: boolean;
  source: string;
  apply_method: string;
  match_score: number;
  match_rationale: string;
  key_matches: string;
  gaps: string;
  cover_letter: string;
  subject_line: string;
  job_description: string;
  status: string;
  date_posted: string;
};

function parseListField(raw: string): string[] {
  try {
    const v = JSON.parse(raw || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function scoreClass(score: number) {
  if (score >= 70) return "badge-success";
  if (score >= 40) return "badge-warning";
  return "badge-error";
}

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [coverLetter, setCoverLetter] = useState("");
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [descExpanded, setDescExpanded] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ type: "success" | "info"; text: string } | null>(null);

  const fetchJob = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/jobs/${id}`);
      if (res.ok) {
        const data = await res.json();
        setJob(data.job);
        setCoverLetter(data.job?.cover_letter || "");
      }
    } catch (err) {
      console.error("Failed to fetch job", err);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (id) fetchJob();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetch(`${API_BASE_URL}/jobs/${id}/generate-letter`, { method: "POST" });
      await fetchJob();
    } catch (err) {
      console.error("Generate letter failed", err);
    }
    setGenerating(false);
  };

  const handleSaveLetter = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const formData = new URLSearchParams();
      formData.append("cover_letter", coverLetter);
      await fetch(`${API_BASE_URL}/jobs/${id}/save-letter`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString(),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      console.error("Save letter failed", err);
    }
    setSaving(false);
  };

  const handleApprove = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/jobs/${id}/approve`, { method: "POST" });
      const url = new URL(res.url);
      if (url.searchParams.get("applied") === "1") {
        setActionMsg({ type: "success", text: `✅ Application email sent successfully!` });
      } else if (url.searchParams.get("applied") === "0") {
        setActionMsg({ type: "info", text: "⚠️ Email send failed — send it manually using the subject and cover letter below." });
      } else if (url.searchParams.get("ats") === "1") {
        setActionMsg({ type: "info", text: '✅ Approved! Open the job link below, paste your cover letter, and click Apply. Then click "Mark Applied".' });
      }
      await fetchJob();
    } catch (err) {
      console.error("Approve failed", err);
    }
  };

  const handleReject = async () => {
    await fetch(`${API_BASE_URL}/jobs/${id}/reject`, { method: "POST" });
    router.push("/jobs");
  };

  const handleMarkApplied = async () => {
    await fetch(`${API_BASE_URL}/jobs/${id}/applied`, { method: "POST" });
    await fetchJob();
  };

  if (loading) {
    return (
      <div className="flex justify-center mt-12">
        <div className="pulse" style={{ width: "20px", height: "20px", borderRadius: "50%", backgroundColor: "var(--accent-blue)" }}></div>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="card-light" style={{ padding: "2rem", textAlign: "center" }}>
        <p className="text-muted">Job not found.</p>
        <Link href="/jobs" className="btn btn-secondary mt-4">← Back to Jobs</Link>
      </div>
    );
  }

  const matches = parseListField(job.key_matches);
  const gaps = parseListField(job.gaps);

  return (
    <div className="animate-fade-in flex flex-col gap-4">
      <div className="flex gap-4">
        <Link href="/jobs" className="text-sm text-[var(--accent-blue)] hover:underline">← Job Queue</Link>
      </div>

      {actionMsg && (
        <div
          className="p-3 rounded-md text-sm"
          style={
            actionMsg.type === "success"
              ? { backgroundColor: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", color: "var(--success)" }
              : { backgroundColor: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", color: "var(--accent-blue)" }
          }
        >
          {actionMsg.text}
        </div>
      )}

      <div className="card-light flex justify-between items-start gap-4 flex-wrap">
        <div>
          <h1 className="text-h3" style={{ fontSize: "1.5rem" }}>{job.job_title}</h1>
          {job.company_url ? (
            <a href={job.company_url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium" style={{ color: "inherit" }}>{job.company_name}</a>
          ) : (
            <div className="text-sm font-medium">{job.company_name}</div>
          )}
          <div className="flex gap-2 flex-wrap items-center mt-2 text-xs">
            {job.location && <span className="text-muted">{job.location}</span>}
            {job.is_remote && <span className="badge badge-success">Remote</span>}
            <span className="badge badge-neutral">{job.source}</span>
            <span className="badge badge-neutral">{job.apply_method.replace("ats_", "")}</span>
            <span className="badge badge-warning" style={{ textTransform: "capitalize" }}>{job.status}</span>
            {job.date_posted && <span className="text-muted">Posted: {job.date_posted}</span>}
          </div>
        </div>
        <span className={`badge ${scoreClass(job.match_score)}`} style={{ fontSize: "1.1rem", padding: "0.5rem 0.9rem" }}>
          {job.match_score}%
        </span>
      </div>

      <div className="card-light">
        <h2 className="text-h3 border-b border-[var(--border-color)] pb-3 mb-3">Match Analysis</h2>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{job.match_rationale}</p>
        {matches.length > 0 && (
          <>
            <div className="text-xs text-muted font-medium mt-3 mb-1">Strengths</div>
            <div className="flex gap-2 flex-wrap">
              {matches.map((m, i) => <span key={i} className="badge badge-success">{m}</span>)}
            </div>
          </>
        )}
        {gaps.length > 0 && (
          <>
            <div className="text-xs text-muted font-medium mt-3 mb-1">Gaps</div>
            <div className="flex gap-2 flex-wrap">
              {gaps.map((g, i) => <span key={i} className="badge badge-error">{g}</span>)}
            </div>
          </>
        )}
      </div>

      <div className="card-light">
        <h2 className="text-h3 border-b border-[var(--border-color)] pb-3 mb-3">How to Apply</h2>
        {job.apply_method === "email" && job.contact_email ? (
          <div className="text-sm">Send email to: <a href={`mailto:${job.contact_email}`} className="text-[var(--accent-blue)]">{job.contact_email}</a></div>
        ) : job.ats_url ? (
          <div className="text-sm">Apply via ATS: <a href={job.ats_url} target="_blank" rel="noopener noreferrer" className="text-[var(--accent-blue)]">{job.ats_url}</a></div>
        ) : (
          <div className="text-sm">Job listing: <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="text-[var(--accent-blue)]">{job.job_url}</a></div>
        )}
      </div>

      <div className="card-light flex flex-col gap-3">
        <div className="flex justify-between items-center border-b border-[var(--border-color)] pb-3">
          <h2 className="text-h3">Cover Letter</h2>
          <button onClick={handleGenerate} className="btn btn-secondary text-xs px-3 py-1" disabled={generating}>
            {generating ? "Generating..." : job.cover_letter ? "↻ Regenerate" : "↻ Generate"}
          </button>
        </div>

        {job.subject_line && (
          <div className="p-2 rounded-md text-sm" style={{ backgroundColor: "var(--bg-main)" }}>
            <div className="text-xs text-muted font-medium mb-1">Email Subject Line</div>
            {job.subject_line}
          </div>
        )}

        <textarea
          className="input"
          rows={12}
          value={coverLetter}
          onChange={(e) => setCoverLetter(e.target.value)}
          style={{ resize: "vertical", fontFamily: "inherit" }}
        />

        <div className="flex gap-2 items-center flex-wrap">
          <button onClick={handleSaveLetter} className="btn btn-primary" disabled={saving}>
            {saving ? "Saving..." : "Save Letter"}
          </button>
          {saved && <span className="text-sm" style={{ color: "var(--success)" }}>Saved.</span>}

          <div style={{ marginLeft: "auto" }} className="flex gap-2">
            {(job.status === "queued" || job.status === "telegram_pending" || job.status === "awaiting_feedback") && (
              <>
                <button onClick={handleApprove} className="btn btn-secondary" style={{ color: "var(--success)", borderColor: "var(--success)" }}>
                  {job.apply_method === "email" && job.contact_email ? "✅ Approve & Send Email" : "✅ Approve"}
                </button>
                <button onClick={handleReject} className="btn btn-secondary" style={{ color: "var(--error)", borderColor: "var(--error)" }}>
                  ✗ Reject
                </button>
              </>
            )}
            {job.status === "approved" && (
              <>
                <a href={job.ats_url || job.job_url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">🔗 Open Job Page</a>
                <button onClick={handleMarkApplied} className="btn btn-primary">✓ Mark Applied</button>
              </>
            )}
            {job.status === "applied" && <span style={{ color: "var(--success)", fontWeight: 600 }}>🎉 Applied!</span>}
          </div>
        </div>
      </div>

      {job.job_description && (
        <div className="card-light">
          <div className="flex justify-between items-center border-b border-[var(--border-color)] pb-3 mb-3">
            <h2 className="text-h3">Job Description</h2>
            <button
              onClick={() => setDescExpanded(!descExpanded)}
              className="text-sm text-[var(--accent-blue)] hover:underline"
              style={{ background: "none", border: "none", cursor: "pointer" }}
            >
              {descExpanded ? "Show less" : "Show more"}
            </button>
          </div>
          <div
            className="text-sm"
            style={{
              color: "var(--text-secondary)", whiteSpace: "pre-wrap",
              maxHeight: descExpanded ? "none" : "200px", overflow: "hidden",
            }}
          >
            {job.job_description}
          </div>
        </div>
      )}
    </div>
  );
}
