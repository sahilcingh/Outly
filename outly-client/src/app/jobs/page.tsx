"use client";

import { useState, useEffect } from "react";

type JobApplication = {
  id: number;
  job_title: string;
  company_name: string;
  job_url: string;
  location: string;
  match_score: number;
  status: string;
  created_at: string;
};

export default function JobsPage() {
  const [resumeText, setResumeText] = useState("");
  const [keywords, setKeywords] = useState("");
  const [location, setLocation] = useState("Remote");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [jobs, setJobs] = useState<JobApplication[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);

  const fetchQueue = async () => {
    try {
      const res = await fetch("/backend/api/jobs/queue");
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
    fetchQueue();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resumeText.trim()) return;

    setLoading(true);
    setError("");
    setSuccess(false);

    try {
      const formData = new URLSearchParams();
      formData.append("resume_text", resumeText);
      formData.append("keywords", keywords);
      formData.append("location", location);
      formData.append("min_score", "60");
      formData.append("remote_only", location.toLowerCase() === "remote" ? "true" : "false");

      const res = await fetch("/backend/jobs", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: formData.toString(),
      });

      if (!res.ok) {
        throw new Error("Failed to start job search.");
      }

      setSuccess(true);
      fetchQueue();
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <h1 className="text-hero" style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>Automated Job Search</h1>
        <p className="text-subhero">Find and apply to jobs that match your skills using AI.</p>
      </div>

      <div className="flex gap-6 flex-wrap lg:flex-nowrap">
        <div className="w-full" style={{ maxWidth: '500px' }}>
          <form className="card-light flex flex-col gap-4" onSubmit={handleSubmit} style={{ padding: '2rem' }}>
            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium">Your Resume / Skills Summary</label>
              <textarea
                className="input"
                placeholder="Paste your resume text here..."
                rows={6}
                value={resumeText}
                onChange={(e) => setResumeText(e.target.value)}
                disabled={loading}
                required
                style={{ resize: 'none' }}
              />
            </div>
            
            <div className="flex flex-col gap-2 mt-4">
              <label className="text-sm font-medium">Keywords (Optional)</label>
              <input
                type="text"
                className="input"
                placeholder="e.g. React, Next.js, FastAPI"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                disabled={loading}
              />
            </div>
            
            <div className="flex flex-col gap-2 mt-4">
              <label className="text-sm font-medium">Location</label>
              <input
                type="text"
                className="input"
                placeholder="e.g. Remote, San Francisco"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                disabled={loading}
              />
            </div>

            <button 
              type="submit" 
              className={`btn btn-primary mt-6 w-full ${loading ? 'pulse' : ''}`}
              disabled={loading}
            >
              {loading ? "Searching..." : "Find Jobs"}
            </button>
            
            {error && (
              <div className="mt-4 p-3 bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.2)] rounded-md text-[var(--error)] text-sm">
                {error}
              </div>
            )}
            
            {success && (
              <div className="mt-4 p-3 bg-[rgba(16,185,129,0.1)] border border-[rgba(16,185,129,0.2)] rounded-md text-[var(--success)] text-sm">
                Search started successfully! Check your queue in a few minutes.
              </div>
            )}
          </form>
        </div>

        <div className="flex-1 w-full">
          <div className="card-light h-full flex flex-col gap-6" style={{ minHeight: '400px' }}>
            <h2 className="text-h3 border-b border-[var(--border-color)] pb-4">Job Queue</h2>

            {queueLoading ? (
              <div className="flex justify-center" style={{ minHeight: '200px', alignItems: 'center' }}>
                <div className="pulse" style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: 'var(--accent-blue)' }}></div>
              </div>
            ) : jobs.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center opacity-50 h-full" style={{ minHeight: '200px' }}>
                 <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-4">
                   <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
                   <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
                 </svg>
                 <h3 className="text-h3 mb-2">No Active Jobs</h3>
                 <p className="text-muted max-w-[250px]">Start a search to find jobs tailored to your resume.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {jobs.map(job => (
                  <a
                    key={job.id}
                    href={job.job_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex justify-between items-start p-3 rounded-md hover:underline"
                    style={{ border: '1px solid var(--border-color)', textDecoration: 'none' }}
                  >
                    <div>
                      <div className="text-sm font-medium">{job.job_title}</div>
                      <div className="text-xs text-muted">{job.company_name} · {job.location}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <span className="badge badge-warning">{job.match_score}% match</span>
                      <span className="text-xs text-muted" style={{ textTransform: 'capitalize' }}>{job.status}</span>
                    </div>
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
