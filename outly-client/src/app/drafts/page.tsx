"use client";

import { useState, useEffect } from "react";

type Draft = {
  id: number;
  company_name: string;
  company_url: string;
  subject: string;
  body: string;
  status: string;
  created_at: string;
};

export default function DraftsPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("draft");

  useEffect(() => {
    fetchDrafts();
  }, [filter]);

  const fetchDrafts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/backend/api/drafts?status=${filter === "all" ? "" : filter}`);
      if (res.ok) {
        const data = await res.json();
        setDrafts(data.drafts || []);
      }
    } catch (err) {
      console.error("Failed to fetch drafts", err);
    }
    setLoading(false);
  };

  const updateDraftStatus = async (id: number, status: string) => {
    try {
      await fetch(`/backend/drafts/${id}/${status}`, {
        method: "POST",
      });
      fetchDrafts(); // Refresh
    } catch (err) {
      console.error("Failed to update status", err);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-hero" style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>Review Drafts</h1>
          <p className="text-subhero">Manage your AI-generated email drafts before sending.</p>
        </div>
        
        <div className="flex gap-2">
          {['all', 'draft', 'approved', 'sent', 'rejected'].map(status => (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={`btn ${filter === status ? 'btn-primary' : 'btn-secondary'} text-xs px-3 py-1`}
              style={{ textTransform: 'capitalize' }}
            >
              {status}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center mt-12">
          <div className="pulse" style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: 'var(--accent-blue)' }}></div>
        </div>
      ) : drafts.length === 0 ? (
        <div className="card-light h-full flex flex-col items-center justify-center text-center opacity-50 mt-8" style={{ minHeight: '300px', borderStyle: 'dashed' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-4">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
          <h3 className="text-h3 mb-2">No Drafts Found</h3>
          <p className="text-muted">No drafts matching status "{filter}".</p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {drafts.map(draft => (
            <div key={draft.id} className="card-light flex flex-col gap-4">
              <div className="flex justify-between items-start border-b border-[var(--border-color)] pb-4">
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="text-h3">{draft.company_name}</h3>
                    <span className={`badge ${
                      draft.status === 'approved' ? 'badge-success' : 
                      draft.status === 'rejected' ? 'badge-error' : 
                      draft.status === 'sent' ? 'badge-success' : 'badge-warning'
                    }`}>
                      {draft.status}
                    </span>
                  </div>
                  {draft.company_url && (
                    <a href={draft.company_url} target="_blank" rel="noopener noreferrer" className="text-sm text-[var(--accent-blue)] hover:underline">
                      {draft.company_url}
                    </a>
                  )}
                  <div className="text-xs text-muted mt-2">Generated: {new Date(draft.created_at).toLocaleString()}</div>
                </div>
                
                <div className="flex gap-2">
                  {draft.status === 'draft' && (
                    <>
                      <button onClick={() => updateDraftStatus(draft.id, 'approve')} className="btn btn-secondary text-[var(--success)]" style={{ borderColor: 'var(--success)' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        Approve
                      </button>
                      <button onClick={() => updateDraftStatus(draft.id, 'reject')} className="btn btn-secondary text-[var(--error)]" style={{ borderColor: 'var(--error)' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        Reject
                      </button>
                    </>
                  )}
                  {draft.status === 'approved' && (
                    <button onClick={() => updateDraftStatus(draft.id, 'sent')} className="btn btn-primary">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                      Mark as Sent
                    </button>
                  )}
                </div>
              </div>
              
              <div className="p-4 rounded-md" style={{ backgroundColor: 'var(--bg-main)', border: '1px solid var(--border-color)' }}>
                <div className="text-sm font-medium mb-3 pb-2 border-b border-[var(--border-color)]">
                  <span className="text-muted">Subject:</span> {draft.subject}
                </div>
                <div className="text-sm whitespace-pre-wrap text-[var(--text-secondary)]">
                  {draft.body}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
