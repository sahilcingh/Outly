import { Reveal } from "../motion-primitives";
import { CopyButton } from "@/components/ui/copy-button";

function CodeBlock({ code }: { code: string }) {
  return (
    <div style={{ position: "relative" }}>
      <pre style={codeBlock}><code>{code}</code></pre>
      <CopyButton code={code} className="absolute top-2 right-2" />
    </div>
  );
}

const codeBlock: React.CSSProperties = {
  backgroundColor: "var(--bg-dark)",
  color: "#e2e8f0",
  border: "1px solid var(--border-dark)",
  borderRadius: "var(--radius-sm)",
  padding: "1rem 1.25rem",
  overflowX: "auto",
  fontSize: "0.82rem",
  lineHeight: 1.6,
  margin: "0.75rem 0",
  fontFamily: "'Fira Code', 'Cascadia Code', monospace",
};

function Endpoint({ method, path, desc }: { method: "GET" | "POST"; path: string; desc: string }) {
  return (
    <div className="card-dark" style={{ padding: "1.25rem 1.5rem", marginBottom: "1rem" }}>
      <span
        className="badge"
        style={{
          backgroundColor: method === "POST" ? "rgba(16,185,129,0.2)" : "rgba(59,130,246,0.2)",
          color: method === "POST" ? "#86efac" : "#93c5fd",
          marginRight: "0.5rem",
        }}
      >
        {method}
      </span>
      <span style={{ fontFamily: "monospace", fontSize: "0.95rem", color: "white" }}>{path}</span>
      <div className="text-sm" style={{ color: "#94a3b8", marginTop: "0.4rem" }}>{desc}</div>
    </div>
  );
}

function ParamTable({ rows }: { rows: { field: string; type: string; required: boolean; desc: string }[] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", margin: "0.75rem 0" }}>
      <thead>
        <tr>
          {["Field", "Type", "Required", "Description"].map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "0.5rem 0.75rem", color: "var(--text-muted)", fontSize: "0.78rem", textTransform: "uppercase", borderBottom: "1px solid var(--border-color)" }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.field}>
            <td style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border-color)", fontFamily: "monospace", color: "var(--accent-blue)" }}>{r.field}</td>
            <td style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border-color)" }}>{r.type}</td>
            <td style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border-color)" }}>
              {r.required ? <span style={{ color: "var(--error)", fontSize: "0.72rem", fontWeight: 600 }}>required</span> : <span className="text-xs text-muted">optional</span>}
            </td>
            <td style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border-color)" }}>{r.desc}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ApiDocsPage() {
  return (
    <div className="flex flex-col gap-2">
      <Reveal className="flex justify-between items-start" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h1 className="text-hero" style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>Outly API Documentation</h1>
          <p className="text-subhero">Integrate AI-powered B2B recruiter outreach into your own tools, CRM, ATS, or workflows.</p>
        </div>
        <a href="/settings/api-keys" className="text-sm text-[var(--accent-blue)] hover:underline">🔑 Manage API Keys</a>
      </Reveal>

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Authentication</h2>
      <p className="text-sm text-muted">
        All API requests require an API key. Generate one at <a href="/settings/api-keys" className="text-[var(--accent-blue)]">Settings → API Keys</a>.
      </p>
      <p className="text-sm text-muted">Pass your key in the <code>Authorization</code> header:</p>
      <CodeBlock code="Authorization: Bearer outly_sk_your_key_here" />
      <p className="text-sm text-muted">Or use the <code>X-API-Key</code> header:</p>
      <CodeBlock code="X-API-Key: outly_sk_your_key_here" />
      <div className="p-3 rounded-md text-sm" style={{ backgroundColor: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", color: "var(--warning)" }}>
        ⚠️ Keep your API key secret. Do not expose it in frontend code or public repositories.
      </div>

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Base URL</h2>
      <div className="text-sm" style={{ fontFamily: "monospace", backgroundColor: "var(--bg-dark)", color: "#86efac", border: "1px solid var(--border-dark)", borderRadius: "var(--radius-sm)", padding: "0.75rem 1rem" }}>
        https://outly-me9j.onrender.com/api/v1
      </div>

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Prospect a Company</h2>
      <Endpoint method="POST" path="/api/v1/prospect" desc="Research a company and draft a personalized recruiter outreach email." />
      <h3 className="text-sm font-medium">Request Body (JSON)</h3>
      <ParamTable rows={[
        { field: "company", type: "string", required: true, desc: "Company name or website URL" },
        { field: "industry", type: "string", required: false, desc: 'Industry hint e.g. "Fintech", "SaaS"' },
        { field: "role", type: "string", required: false, desc: "Candidate role to offer (auto-detected if omitted)" },
      ]} />
      <h3 className="text-sm font-medium">Example Request</h3>
      <CodeBlock code={`curl -X POST https://outly-me9j.onrender.com/api/v1/prospect \\
  -H "Authorization: Bearer outly_sk_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "company": "Razorpay",
    "industry": "Fintech",
    "role": "Senior Backend Engineer"
  }'`} />
      <h3 className="text-sm font-medium">Example Response</h3>
      <CodeBlock code={`{
  "success": true,
  "company_name": "Razorpay",
  "company_url": "https://razorpay.com",
  "contact_title": "Head of Talent Acquisition",
  "contact_name": "Priya Sharma",
  "contact_email": null,
  "role_to_offer": "Senior Backend Engineer",
  "subject": "Vetted Backend Engineer for Razorpay's Payment Infrastructure",
  "body": "Hi Priya,\\n\\nI'm a specialist recruitment consultant reaching out...",
  "rationale": "Razorpay is scaling its payment infrastructure and actively hiring backend engineers.",
  "hiring_signals": ["Senior Backend Engineer", "Platform Engineer"],
  "news_signals": ["Razorpay raises $375M Series F"],
  "from_cache": false
}`} />

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Prospect from Resume</h2>
      <Endpoint method="POST" path="/api/v1/resume" desc="Find matching companies for a candidate and draft outreach emails for all of them." />
      <h3 className="text-sm font-medium">Request Body (JSON)</h3>
      <ParamTable rows={[
        { field: "resume_text", type: "string", required: true, desc: "Candidate's resume or LinkedIn summary as plain text" },
        { field: "industry", type: "string", required: false, desc: 'Industry focus e.g. "Fintech", "Healthcare"' },
        { field: "max_companies", type: "integer", required: false, desc: "Number of companies to target, 1–10 (default: 5)" },
      ]} />
      <h3 className="text-sm font-medium">Example Request</h3>
      <CodeBlock code={`curl -X POST https://outly-me9j.onrender.com/api/v1/resume \\
  -H "Authorization: Bearer outly_sk_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "resume_text": "Senior Java engineer with 6 years experience in Spring Boot, Kafka, PostgreSQL. Previously at Flipkart and Swiggy.",
    "industry": "Fintech",
    "max_companies": 5
  }'`} />
      <h3 className="text-sm font-medium">Example Response</h3>
      <CodeBlock code={`{
  "success": true,
  "count": 5,
  "drafts": [
    {
      "company_name": "Razorpay",
      "company_url": "https://razorpay.com",
      "contact_title": "Head of Engineering",
      "role_to_offer": "Senior Java Backend Engineer",
      "subject": "Strong Java Engineer for Razorpay's Backend",
      "body": "Hi...",
      "rationale": "..."
    },
    ...
  ]
}`} />

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>List Drafts</h2>
      <Endpoint method="GET" path="/api/v1/drafts" desc="List your saved drafts. Supports filtering and pagination." />
      <h3 className="text-sm font-medium">Query Parameters</h3>
      <ParamTable rows={[
        { field: "status", type: "string", required: false, desc: "Filter: draft | approved | sent | rejected" },
        { field: "limit", type: "integer", required: false, desc: "Max results (default: 20)" },
      ]} />
      <h3 className="text-sm font-medium">Example</h3>
      <CodeBlock code={`curl https://outly-me9j.onrender.com/api/v1/drafts?status=approved \\
  -H "Authorization: Bearer outly_sk_your_key"`} />

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Get a Draft</h2>
      <Endpoint method="GET" path="/api/v1/drafts/{id}" desc="Retrieve a single draft by its ID." />
      <h3 className="text-sm font-medium">Example</h3>
      <CodeBlock code={`curl https://outly-me9j.onrender.com/api/v1/drafts/42 \\
  -H "Authorization: Bearer outly_sk_your_key"`} />

      <h2 className="text-h3" style={{ marginTop: "2rem" }}>Error Responses</h2>
      <ParamTable rows={[
        { field: "401", type: "", required: false, desc: "Invalid or missing API key" },
        { field: "400", type: "", required: false, desc: "Bad request: missing required fields" },
        { field: "404", type: "", required: false, desc: "Draft not found" },
        { field: "422", type: "", required: false, desc: "No draft generated: insufficient company data" },
        { field: "500", type: "", required: false, desc: "Internal server error" },
      ]} />
      <CodeBlock code={`{ "success": false, "error": "Description of the error" }`} />
    </div>
  );
}
