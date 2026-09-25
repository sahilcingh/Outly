"use client";

import { useState, useRef, useEffect } from "react";
import { API_BASE_URL } from "../config";
import { Reveal, StaggerList, StaggerItem, PopIn, AnimatePresence, fadeUp, motion } from "../motion-primitives";
import { ExternalLink } from "@/components/ui/external-link";
import { CopyButton } from "@/components/ui/copy-button";

type EventItem = { step: string; label: string; detail: string };

type DraftResult = {
  company_name?: string;
  company_url?: string;
  candidate_role?: string;
  candidate_skills?: string[];
  subject?: string;
  body?: string;
  rationale?: string;
  from_cache?: boolean;
};

const STEP_LABELS: Record<string, string> = {
  analyzing_resume: "🔍 Extracting skills from resume...",
  profile_ready: "✅ Candidate profile extracted",
  finding_companies: "🏢 Finding matching companies via AI...",
  verifying_companies: "🔗 Verifying company websites...",
  companies_found: "✅ Companies verified",
  prospecting: "✍️ Researching & drafting...",
  done: "🎉 All drafts ready!",
};

type DraftCardState = { subject: string; body: string; saveState: "idle" | "saving" | "saved" | "error" };

export default function ResumePage() {
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumeText, setResumeText] = useState("");
  const [industry, setIndustry] = useState("");
  const [maxCompanies, setMaxCompanies] = useState(6);

  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [drafts, setDrafts] = useState<DraftResult[] | null>(null);
  const [cardState, setCardState] = useState<DraftCardState[]>([]);
  const [error, setError] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

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
          const results: DraftResult[] = data.result || [];
          setDrafts(results);
          setCardState(results.map((d) => ({ subject: d.subject || "", body: d.body || "", saveState: "idle" })));
          setLoading(false);
          sse.close();
        } else if (data.step === "error") {
          setError(data.detail || data.label || "Resume pipeline failed.");
          setLoading(false);
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
      setError("Connection lost. Please try again.");
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
    setEvents([]);
    setDrafts(null);
    setCardState([]);

    try {
      const formData = new FormData();
      if (resumeFile) formData.append("resume_file", resumeFile);
      formData.append("resume_text", resumeText);
      formData.append("industry", industry);
      formData.append("max_companies", String(Math.min(Math.max(maxCompanies, 1), 10)));

      const res = await fetch(`${API_BASE_URL}/resume`, { method: "POST", body: formData });
      if (!res.ok) throw new Error("Failed to start resume search.");

      const jobId = new URL(res.url).searchParams.get("job_id");
      if (!jobId) throw new Error("Please upload a PDF resume or paste your resume text.");
      startSSE(jobId);
    } catch (err: any) {
      setLoading(false);
      setError(err.message || "An error occurred");
    }
  };

  const updateCard = (i: number, patch: Partial<DraftCardState>) => {
    setCardState((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  };

  const handleSaveDraft = async (i: number) => {
    const draft = drafts?.[i];
    const card = cardState[i];
    if (!draft || !card) return;
    updateCard(i, { saveState: "saving" });
    try {
      const formData = new URLSearchParams();
      formData.append("company_name", draft.company_name || "");
      formData.append("company_url", draft.company_url || "");
      formData.append("subject", card.subject);
      formData.append("body", card.body);
      formData.append("rationale", draft.rationale || "");

      const res = await fetch(`${API_BASE_URL}/draft/save`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString(),
        credentials: "include",
      });
      updateCard(i, { saveState: res.ok ? "saved" : "error" });
    } catch {
      updateCard(i, { saveState: "error" });
    }
  };

  return (
    <div>
      <Reveal className="mb-6">
        <h1 className="text-hero" style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>Resume Prospecting</h1>
        <p className="text-subhero">Upload a candidate&apos;s resume, and Outly finds matching companies and drafts a personalized outreach email for each one.</p>
      </Reveal>

      <motion.form
        initial="hidden" animate="show" variants={fadeUp} transition={{ delay: 0.1 }}
        className="card-light flex flex-col gap-4" onSubmit={handleSubmit} style={{ maxWidth: "560px" }}
      >
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
              accept=".pdf,.txt"
              style={{ display: "none" }}
              disabled={loading}
              onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
            />
            {resumeFile ? resumeFile.name : "Click to upload a PDF or TXT resume"}
          </label>
          <div className="text-xs text-muted text-center">or paste resume text below</div>
          <textarea
            className="input"
            placeholder="Paste candidate's resume, LinkedIn summary, or skills list here..."
            rows={5}
            value={resumeText}
            onChange={(e) => setResumeText(e.target.value)}
            disabled={loading}
            style={{ resize: "none" }}
          />
        </div>

        <div className="flex gap-4 flex-wrap">
          <div className="flex flex-col gap-2" style={{ flex: "1 1 180px" }}>
            <label className="text-sm font-medium">Industry Focus <span className="text-xs text-muted">(optional)</span></label>
            <input
              type="text" className="input" placeholder="e.g. Fintech, SaaS, Healthcare"
              value={industry} onChange={(e) => setIndustry(e.target.value)} disabled={loading}
            />
          </div>
          <div className="flex flex-col gap-2" style={{ flex: "1 1 180px" }}>
            <label className="text-sm font-medium">Number of Companies</label>
            <select
              className="input"
              value={maxCompanies}
              onChange={(e) => setMaxCompanies(Number(e.target.value))}
              disabled={loading}
            >
              <option value={4}>4 companies</option>
              <option value={6}>6 companies</option>
              <option value={8}>8 companies</option>
              <option value={10}>10 companies</option>
            </select>
          </div>
        </div>

        <button type="submit" className={`btn btn-primary w-full ${loading ? "pulse" : ""}`} disabled={loading}>
          {loading ? "Searching..." : "🔍 Find Companies & Draft Emails"}
        </button>

        <AnimatePresence>
        {error && (
          <PopIn className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }}>
            {error}
          </PopIn>
        )}
        </AnimatePresence>

        {loading && events.length > 0 && (
          <StaggerList className="flex flex-col gap-1">
            {events.map((ev, i) => (
              <StaggerItem key={i} className="text-xs text-muted flex gap-2">
                <span>{ev.label}</span>
                {ev.detail && <span style={{ opacity: 0.7 }}>· {ev.detail}</span>}
              </StaggerItem>
            ))}
          </StaggerList>
        )}
      </motion.form>

      {drafts && (
        <Reveal className="mt-6" style={{ marginTop: "2rem" }}>
          <h2 className="text-h3 mb-4" style={{ marginBottom: "1rem" }}>
            {drafts.length > 0 ? `✅ ${drafts.length} draft${drafts.length > 1 ? "s" : ""} ready` : "No drafts generated"}
          </h2>

          {drafts.length === 0 && (
            <div className="card-light" style={{ textAlign: "center", color: "var(--text-muted)" }}>
              No drafts could be generated. The companies found may already be in the database or had insufficient web content.
            </div>
          )}

          <StaggerList className="flex flex-col gap-6">
            {drafts.map((draft, i) => {
              const card = cardState[i];
              if (!card) return null;
              const skills = (draft.candidate_skills || []).slice(0, 6);
              return (
                <StaggerItem key={i} className="card-light card-hover flex flex-col gap-3">
                  <div className="flex justify-between items-start border-b border-[var(--border-color)] pb-3">
                    <div>
                      <div className="flex items-center gap-3">
                        <h3 className="text-h3">{draft.company_name || draft.company_url}</h3>
                        {draft.from_cache && <span className="badge badge-warning">📦 from database</span>}
                      </div>
                      {draft.company_url && (
                        <ExternalLink href={draft.company_url} className="text-[var(--accent-blue)]">
                          {draft.company_url}
                        </ExternalLink>
                      )}
                    </div>
                    {draft.candidate_role && (
                      <span className="text-xs font-medium" style={{ color: "var(--accent-blue)" }}>{draft.candidate_role}</span>
                    )}
                  </div>

                  {skills.length > 0 && (
                    <div className="flex gap-2 flex-wrap">
                      {skills.map((s, si) => (
                        <span key={si} className="badge badge-neutral">{s}</span>
                      ))}
                    </div>
                  )}

                  <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium">Subject</label>
                    <input
                      type="text" className="input"
                      value={card.subject}
                      onChange={(e) => updateCard(i, { subject: e.target.value })}
                    />
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium">Body <span className="text-xs text-muted">(editable)</span></label>
                    <textarea
                      className="input" rows={8}
                      value={card.body}
                      onChange={(e) => updateCard(i, { body: e.target.value })}
                      style={{ resize: "vertical", fontFamily: "inherit" }}
                    />
                  </div>

                  {draft.rationale && (
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      🧠 <strong>Rationale:</strong> {draft.rationale}
                    </div>
                  )}

                  <div className="flex gap-2 items-center">
                    <button onClick={() => handleSaveDraft(i)} className="btn btn-primary" disabled={card.saveState === "saving"}>
                      {card.saveState === "saving" ? "Saving..." : "💾 Save Draft"}
                    </button>
                    <div className="flex items-center gap-1" style={{ border: "1px solid var(--text-primary)", borderRadius: "var(--radius-sm)", padding: "0 0.25rem 0 1rem", height: "2.4rem" }}>
                      <span className="text-sm font-medium">Copy</span>
                      <CopyButton code={card.body} className="!bg-transparent !border-0 !text-[var(--text-primary)] hover:!bg-[var(--border-color)] hover:!text-[var(--text-primary)]" />
                    </div>
                    {card.saveState === "saved" && <span className="text-sm" style={{ color: "var(--success)" }}>Saved.</span>}
                    {card.saveState === "error" && <span className="text-sm" style={{ color: "var(--error)" }}>Failed to save.</span>}
                  </div>
                </StaggerItem>
              );
            })}
          </StaggerList>
        </Reveal>
      )}
    </div>
  );
}
