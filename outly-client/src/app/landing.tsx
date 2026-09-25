"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Code2,
  FileText,
  Layers,
  PenLine,
  Plus,
  Search,
  Sparkles,
  Target,
} from "lucide-react";
import { EASE } from "./motion-primitives";
import { useAuth } from "./auth-context";
import ThemeToggle from "./ThemeToggle";
import { OutlyMark } from "@/components/outly-mark";
import styles from "./landing.module.css";

/* -------------------------------------------------------------- content -- */

/** The real pipeline steps from the backend's _STEP_LABELS, replayed on a loop. */
const PIPELINE = [
  { time: "00:00", label: "Searching for official website", detail: "query: razorpay" },
  { time: "00:03", label: "Website found", detail: "razorpay.com" },
  { time: "00:06", label: "Scraping website content", detail: "careers · about · engineering" },
  { time: "00:12", label: "Fetching hiring signals & recent news", detail: "ATS boards + press" },
  { time: "00:19", label: "Analyzing tech stack & role fit", detail: "weighing the evidence" },
  { time: "00:25", label: "Looking for contact person", detail: "talent + engineering leads" },
  { time: "00:30", label: "Writing personalized email", detail: "grounded in what it found" },
  { time: "00:34", label: "Draft ready", detail: "" },
];

const SOURCES = [
  "LinkedIn",
  "Indeed",
  "Glassdoor",
  "Google Jobs",
  "Careers Pages",
  "ATS Boards",
  "Company Sites",
  "News Signals",
  "Telegram",
  "REST API",
  "CSV Batch",
];

const STATS = [
  { value: "4", label: "Sources swept", note: "LinkedIn · Indeed · Glassdoor · Google" },
  { value: "0–100", label: "Match score", note: "On every role, with its reasoning" },
  { value: "2×", label: "Digest daily", note: "Weekdays, 9:30 & 14:30 IST" },
  { value: "3h", label: "Freshness window", note: "Widened to 24h only if empty" },
];

const OUTBOUND = [
  "Finds the real official website from nothing but a name",
  "Scrapes the site, the careers page and the ATS boards behind it",
  "Pulls recent news and live hiring signals",
  "Reads the tech stack and picks the role worth offering",
  "Identifies the person who should actually receive this",
  "Writes the subject and body from the evidence, not a template",
];

const INBOUND = [
  "Parses your resume into a working candidate profile",
  "Sweeps LinkedIn, Indeed, Glassdoor and Google Jobs",
  "Strips internships, over-level roles and known staffing spam",
  "Scores every survivor 0–100 with its reasons and your gaps",
  "Writes a cover letter tailored to the posting you'd apply to",
  "Sends it by email on approval, or hands you the ATS link",
];

const TRAIL = [
  { n: "01", title: "Point", desc: "Give it a company name, a resume, or a CSV of either." },
  { n: "02", title: "Collect", desc: "Official sites, careers pages, ATS boards, press, four job boards." },
  { n: "03", title: "Weigh", desc: "The model scores the fit, surfaces the signal, and names the gaps." },
  { n: "04", title: "Write", desc: "A subject and body built from the evidence trail, not a merge field." },
  { n: "05", title: "Act", desc: "Edit, save, send, or open the ATS. The last call is always yours." },
];

const FEATURES = [
  {
    icon: Search,
    title: "Company dossiers",
    desc: "Open roles, recent press, tech stack and the contact most likely to reply, assembled from nothing but a name.",
  },
  {
    icon: FileText,
    title: "Resume prospecting",
    desc: "Hand it a candidate's resume. It proposes matching companies, verifies each one is real, then drafts outreach for all of them.",
  },
  {
    icon: Target,
    title: "Match scoring",
    desc: "Every role gets a 0–100 score with the specific reasons it fits and the gaps you'd have to talk your way around.",
  },
  {
    icon: PenLine,
    title: "Tailored cover letters",
    desc: "Written against the actual posting and your actual history. Fully editable before anything leaves the building.",
  },
  {
    icon: Layers,
    title: "Batch runs",
    desc: "Upload a CSV and the full pipeline runs per row. Companies already drafted return from cache instead of burning tokens.",
  },
  {
    icon: Code2,
    title: "REST API",
    desc: "Every pipeline is an endpoint. Drop Outly straight into your ATS, your CRM, or a script you wrote yourself.",
  },
];

const FILTERS = [
  { key: "Geo", val: "India only, remote listings included", status: "Active" },
  { key: "Internships", val: "Blocked outright, at every seniority", status: "Active" },
  { key: "Experience", val: "Skips postings demanding more years than you have", status: "Active" },
  { key: "Seniority", val: "Over-level roles dropped, not down-ranked", status: "Strict" },
  { key: "Score floor", val: "55 by default · 68 for entry-level profiles", status: "Active" },
  { key: "Freshness", val: "3-hour window, widened to 24h only when empty", status: "Active" },
  { key: "Blocklist", val: "Known staffing-spam outfits, permanently excluded", status: "Active" },
  { key: "Dedupe", val: "A job you have already seen never appears twice", status: "Active" },
];

const AUTOMATION = [
  {
    icon: Clock,
    title: "Weekdays, 9:30 and 14:30 IST",
    desc: "Twenty matches on Monday, ten every other day. No tab needs to be open.",
  },
  {
    icon: FileText,
    title: "Delivered as a PDF",
    desc: "The whole digest (scores, rationale, apply links) in a single file you can read on a phone.",
  },
  {
    icon: CheckCircle2,
    title: "Approve or reject inline",
    desc: "Tap a button in the chat. Approved applications with an email address send themselves.",
  },
  {
    icon: Sparkles,
    title: "Or just talk to it",
    desc: "“search now”, “only show me 70+ matches”, “location Mumbai”. It works out what you meant.",
  },
];

const ENDPOINTS = [
  { method: "POST", path: "/api/v1/prospect" },
  { method: "POST", path: "/api/v1/resume" },
  { method: "POST", path: "/api/v1/batch" },
  { method: "GET", path: "/api/v1/drafts" },
  { method: "GET", path: "/api/v1/jobs/queue" },
];

const FAQ = [
  {
    q: "What do I actually have to give it?",
    a: "A company name, a resume PDF, or a CSV. That is the whole input. Outly finds the official website, the open roles, the recent news and the right contact on its own. You never paste a URL or fill in a template.",
  },
  {
    q: "Does it send email on my behalf?",
    a: "Only once you approve. Recruiter outreach always lands in Drafts to be edited first. On the candidate side, if a posting exposes an email address and you hit Approve, Outly sends the application over SMTP and marks it applied. Anything living on an ATS gets handed to you as a link instead.",
  },
  {
    q: "Which job boards does it search?",
    a: "LinkedIn, Indeed, Glassdoor and Google Jobs, filtered to India, checked for freshness, and deduplicated against everything already sitting in your queue.",
  },
  {
    q: "How is the match score worked out?",
    a: "A language model reads the full posting against your parsed resume and returns a 0–100 score alongside the concrete matches and the gaps. Anything under the floor (55 by default, 68 for entry-level profiles, because junior searches are far noisier) never reaches you at all.",
  },
  {
    q: "Can I change what gets filtered out?",
    a: "Yes. Search location, minimum score, remote-only mode and your experience ceiling are all adjustable, either from the Telegram bot or through the API. The defaults are opinionated, not fixed.",
  },
  {
    q: "Is there an API?",
    a: "Every pipeline is a REST endpoint authenticated with an outly_sk_ key, passed as a bearer token or an X-API-Key header. Prospect a company, run a resume, queue a batch, or pull your drafts and job queue back out.",
  },
];

/* ------------------------------------------------------------- helpers --- */

function Rise({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ duration: 0.6, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/* --------------------------------------------------------------- page ---- */

export default function Landing() {
  const { email } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  // Starts at 1 so the terminal is never an empty box on first paint.
  const [step, setStep] = useState(1);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // One timer, re-armed by its own state change: advance a step, then restart.
  // Reduced motion jumps straight to the finished state and stops there.
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const done = step >= PIPELINE.length;
    if (reduce && done) return;
    const id = setTimeout(
      () => setStep(reduce ? PIPELINE.length : done ? 1 : step + 1),
      reduce ? 0 : done ? 3600 : 780,
    );
    return () => clearTimeout(id);
  }, [step]);

  const finished = step >= PIPELINE.length;
  const primaryHref = email ? "/prospecting" : "/login";
  const primaryLabel = email ? "Open workspace" : "Get started";

  return (
    <div className={styles.page}>
      {/* ---------------------------------------------------------- nav -- */}
      <nav className={`${styles.nav} ${scrolled ? styles.navScrolled : ""}`}>
        <div className={styles.shell}>
          <div className={styles.navInner}>
            <Link href="/" className={styles.brand}>
              <OutlyMark size={30} className={styles.brandMark} />
              <span className={styles.brandName}>Outly</span>
              <span className={styles.brandSub}>Intelligence</span>
            </Link>

            <div className={styles.navLinks}>
              <a href="#modes" className={styles.navLink}>Product</a>
              <a href="#trail" className={styles.navLink}>How it works</a>
              <a href="#filters" className={styles.navLink}>Filters</a>
              <a href="#automation" className={styles.navLink}>Automation</a>
              <a href="#api" className={styles.navLink}>API</a>
            </div>

            <div className={styles.navActions}>
              <ThemeToggle />
              {!email && (
                <Link href="/login" className={`${styles.btn} ${styles.btnGhost}`}>
                  Sign in
                </Link>
              )}
              <Link href={primaryHref} className={`${styles.btn} ${styles.btnSolid}`}>
                {primaryLabel}
                <ArrowRight size={15} strokeWidth={2.4} />
              </Link>
            </div>
          </div>
        </div>
      </nav>

      {/* --------------------------------------------------------- hero -- */}
      <header className={styles.hero}>
        <div className={styles.heroGrid} aria-hidden />
        <div className={styles.heroGlow} aria-hidden />
        <div className={`${styles.heroGlow} ${styles.heroGlowAlt}`} aria-hidden />

        <div className={styles.shell}>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: EASE }}
          >
            <span className={styles.chip}>
              <i className={styles.chipDot} />
              Live · Agent online
            </span>

            <h1 className={styles.heroTitle}>
              Find the opening.
              <br />
              Write the <em>opener</em>.
            </h1>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.12, ease: EASE }}
          >
            <p className={styles.heroSub}>
              Outly is an autonomous research agent. Point it at a company or hand it a
              resume, and it reads the websites, careers pages, ATS boards and job boards,
              weighs what it finds, and gives you back{" "}
              <strong>an email that is ready to send</strong>. Not a template with your
              name dropped in.
            </p>

            <div className={styles.heroCtas}>
              <Link href={primaryHref} className={`${styles.btn} ${styles.btnSolid} ${styles.btnLg}`}>
                {email ? "Open workspace" : "Start investigating"}
                <ArrowRight size={17} strokeWidth={2.4} />
              </Link>
              <a href="#modes" className={`${styles.btn} ${styles.btnGhost} ${styles.btnLg}`}>
                See how it works
              </a>
            </div>

            <p className={styles.heroNote}>
              A company name, a resume PDF, or a CSV. That is the entire input
            </p>
          </motion.div>

          {/* Live pipeline replay */}
          <motion.div
            className={styles.terminal}
            initial={{ opacity: 0, y: 34 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.24, ease: EASE }}
          >
            <div className={styles.terminalBar}>
              <span className={styles.terminalDots}>
                <span />
                <span />
                <span />
              </span>
              <span className={styles.terminalTitle}>outly investigate “Razorpay”</span>
              <span className={styles.terminalLive}>
                <i />
                Streaming
              </span>
            </div>

            <div className={styles.terminalBody}>
              {PIPELINE.slice(0, step).map((line, i) => {
                const isLast = i === step - 1;
                const isDone = i === PIPELINE.length - 1;
                return (
                  <div
                    key={line.label}
                    className={`${styles.termLine} ${isLast && !finished ? styles.termActive : ""}`}
                  >
                    <span className={styles.termTime}>{line.time}</span>
                    <span className={`${styles.termGlyph} ${isDone ? styles.termGlyphDone : ""}`} />
                    <span>
                      {line.label}
                      {line.detail && <span className={styles.termDetail}> · {line.detail}</span>}
                    </span>
                  </div>
                );
              })}

              {!finished && (
                <div className={styles.termLine}>
                  <span className={styles.termTime}>{PIPELINE[step]?.time}</span>
                  <span className={styles.termCaret} />
                </div>
              )}

              {finished && (
                <div className={styles.termResult}>
                  <div className={styles.termResultHead}>
                    <span>Draft ready</span>
                    <span>Evidence: 4 signals</span>
                  </div>
                  <div className={styles.termResultGrid}>
                    <div>
                      <span className={styles.termKey}>Open roles found</span>
                      <span className={styles.termVal}>4</span>
                    </div>
                    <div>
                      <span className={styles.termKey}>Target contact</span>
                      <span className={styles.termVal}>Head of Talent</span>
                    </div>
                    <div>
                      <span className={styles.termKey}>Role to offer</span>
                      <span className={styles.termVal}>Senior Backend Engineer</span>
                    </div>
                  </div>
                  <p className={styles.termSubject}>
                    <span className={styles.termKey}>Subject</span>
                    Vetted backend engineer for your payments infrastructure
                  </p>
                </div>
              )}
            </div>
          </motion.div>

          {/* Stats */}
          <div className={styles.stats}>
            {STATS.map((s, i) => (
              <Rise key={s.label} delay={i * 0.06} className={styles.statItem}>
                <div className={styles.statValue}>{s.value}</div>
                <div className={styles.statLabel}>{s.label}</div>
                <div className={styles.statNote}>{s.note}</div>
              </Rise>
            ))}
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------ marquee -- */}
      <div className={styles.marquee}>
        <div className={styles.marqueeTrack}>
          {[...SOURCES, ...SOURCES].map((src, i) => (
            <span key={i} className={styles.marqueeItem}>
              {src}
            </span>
          ))}
        </div>
      </div>

      {/* -------------------------------------------------------- modes -- */}
      <section id="modes" className={styles.section}>
        <div className={styles.shell}>
          <Rise className={styles.sectionHead}>
            <span className={styles.overline}>01 / Two directions</span>
            <h2 className={styles.sectionTitle}>One agent. Both sides of the table.</h2>
            <p className={styles.sectionSub}>
              It is the same research pipeline, run in reverse depending on who you are.
              Recruiters point it at companies. Candidates point it at themselves.
            </p>
          </Rise>

          <div className={styles.modes}>
            <Rise className={styles.modeCard}>
              <span className={styles.modeTag}>Outbound · Recruiters &amp; founders</span>
              <h3 className={styles.modeTitle}>You are pitching talent.</h3>
              <p className={styles.modeDesc}>
                Name a company. Outly builds the dossier and writes the email that earns a
                reply, because it already knows what they are hiring for.
              </p>
              <Flow items={OUTBOUND} />
              <div className={styles.chips}>
                {["Batch CSV", "Duplicate guard", "Editable before send", "Saved to drafts"].map((c) => (
                  <span key={c} className={styles.chipSm}>{c}</span>
                ))}
              </div>
            </Rise>

            <Rise delay={0.1} className={`${styles.modeCard} ${styles.modeCardDark}`}>
              <span className={styles.modeTag}>Inbound · Candidates</span>
              <h3 className={styles.modeTitle}>You are the talent.</h3>
              <p className={styles.modeDesc}>
                Upload a resume once. Outly hunts the boards on a schedule and applies in
                your voice, and never to a role it cannot justify.
              </p>
              <Flow items={INBOUND} />
              <div className={styles.chips}>
                {["One-click apply", "Telegram digest", "PDF export", "Approval queue"].map((c) => (
                  <span key={c} className={styles.chipSm}>{c}</span>
                ))}
              </div>
            </Rise>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- trail -- */}
      <section id="trail" className={styles.sectionTight}>
        <div className={styles.shell}>
          <Rise className={styles.sectionHead}>
            <span className={styles.overline}>02 / The evidence trail</span>
            <h2 className={styles.sectionTitle}>Nothing gets written before it gets proven.</h2>
          </Rise>

          <div className={styles.trail}>
            {TRAIL.map((t, i) => (
              <Rise key={t.n} delay={i * 0.07} className={styles.trailItem}>
                <div className={styles.trailNum}>{t.n}</div>
                <div className={styles.trailTitle}>{t.title}</div>
                <p className={styles.trailDesc}>{t.desc}</p>
              </Rise>
            ))}
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------- features -- */}
      <section className={styles.sectionTight}>
        <div className={styles.shell}>
          <Rise className={styles.sectionHead}>
            <span className={styles.overline}>03 / Capabilities</span>
            <h2 className={styles.sectionTitle}>Six things it does without being asked twice.</h2>
          </Rise>

          <div className={styles.features}>
            {FEATURES.map((f, i) => (
              <Rise key={f.title} delay={(i % 3) * 0.07} className={styles.feature}>
                <div className={styles.featureIcon}>
                  <f.icon size={19} strokeWidth={1.9} />
                </div>
                <h3 className={styles.featureTitle}>{f.title}</h3>
                <p className={styles.featureDesc}>{f.desc}</p>
              </Rise>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ filters -- */}
      <section id="filters" className={styles.band}>
        <div className={styles.bandGlow} aria-hidden />
        <div className={styles.shell}>
          <div className={styles.bandGrid}>
            <Rise>
              <span className={styles.overline}>04 / Opinionated by default</span>
              <h2 className={styles.sectionTitle}>
                The best filter is the one that deletes things.
              </h2>
              <p className={styles.sectionSub}>
                Most tools optimise for volume. Outly throws away almost everything it
                finds, deliberately, so that what does reach you is worth the thirty
                seconds it takes to read.
              </p>
              <p className={styles.sectionSub} style={{ marginTop: "1.5rem" }}>
                Location, minimum score, remote-only and your experience ceiling are all
                tunable, from Telegram or the API.
              </p>
            </Rise>

            <Rise delay={0.12}>
              <div className={styles.console}>
                <div className={styles.consoleHead}>
                  <span>Filters active</span>
                  <span>{FILTERS.length} rules</span>
                </div>
                {FILTERS.map((f) => (
                  <div key={f.key} className={styles.consoleRow}>
                    <span className={styles.consoleKey}>{f.key}</span>
                    <span className={styles.consoleVal}>{f.val}</span>
                    <span className={styles.consoleStatus}>{f.status}</span>
                  </div>
                ))}
              </div>
            </Rise>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- automation -- */}
      <section id="automation" className={styles.section}>
        <div className={styles.shell}>
          <div className={styles.split}>
            <Rise>
              <span className={styles.overline}>05 / Automation</span>
              <h2 className={styles.sectionTitle}>It keeps working after you close the tab.</h2>
              <p className={styles.sectionSub}>
                A scheduler runs the entire search twice a day and delivers the results
                where you already are.
              </p>

              <div className={styles.bullets}>
                {AUTOMATION.map((b) => (
                  <div key={b.title} className={styles.bullet}>
                    <span className={styles.bulletIcon}>
                      <b.icon size={17} strokeWidth={2} />
                    </span>
                    <span>
                      <span className={styles.bulletTitle}>{b.title}</span>
                      <p className={styles.bulletDesc}>{b.desc}</p>
                    </span>
                  </div>
                ))}
              </div>
            </Rise>

            <Rise delay={0.12}>
              <div className={styles.chat}>
                <div className={styles.chatHead}>
                  <span className={styles.chatAvatar}>O</span>
                  <span>
                    <span className={styles.chatName}>Outly Job Bot</span>
                    <br />
                    <span className={styles.chatStatus}>online</span>
                  </span>
                </div>

                <div className={`${styles.bubble} ${styles.bubbleBot}`}>
                  <div className={styles.tgFile}>
                    <FileText size={18} strokeWidth={1.8} color="var(--accent-blue)" />
                    <span>
                      <span className={styles.tgFileName}>job-digest.pdf</span>
                      <br />
                      <span className={styles.tgFileMeta}>10 matches · top score 87</span>
                    </span>
                  </div>
                  Senior Backend Engineer at Razorpay. Match score <strong>87</strong>. Strong Python
                  and payments overlap; no Kafka on your resume.
                  <div className={styles.tgBtns}>
                    <span className={`${styles.tgBtn} ${styles.tgBtnOk}`}>Approve</span>
                    <span className={`${styles.tgBtn} ${styles.tgBtnNo}`}>Reject</span>
                    <span className={`${styles.tgBtn} ${styles.tgBtnGo}`}>Apply ↗</span>
                  </div>
                  <div className={styles.chatTime}>09:30</div>
                </div>

                <div className={`${styles.bubble} ${styles.bubbleUser}`}>
                  only show me 70+ matches
                </div>

                <div className={`${styles.bubble} ${styles.bubbleBot}`}>
                  Minimum match score set to <strong>70</strong>. Jobs below that will be
                  skipped from the next search onward.
                  <div className={styles.chatTime}>09:31</div>
                </div>
              </div>
            </Rise>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- api -- */}
      <section id="api" className={styles.sectionTight}>
        <div className={styles.shell}>
          <div className={styles.split}>
            <Rise>
              <span className={styles.overline}>06 / Build on it</span>
              <h2 className={styles.sectionTitle}>Every pipeline is one POST away.</h2>
              <p className={styles.sectionSub}>
                Authenticate with an <code>outly_sk_</code> key and run the same research
                from your ATS, your CRM, or a cron job you wrote yourself.
              </p>

              <div className={styles.endpoints}>
                {ENDPOINTS.map((e) => (
                  <span key={e.path} className={styles.endpoint}>
                    <span className={`${styles.method} ${e.method === "GET" ? styles.methodGet : ""}`}>
                      {e.method}
                    </span>
                    {e.path}
                  </span>
                ))}
              </div>

              <div style={{ marginTop: "1.8rem" }}>
                <Link href="/api-docs" className={`${styles.btn} ${styles.btnGhost}`}>
                  Read the API docs
                  <ArrowUpRight size={15} strokeWidth={2.2} />
                </Link>
              </div>
            </Rise>

            <Rise delay={0.12}>
              <div className={styles.codeCard}>
                <div className={styles.codeHead}>
                  <span>POST /api/v1/prospect</span>
                  <span>bash</span>
                </div>
                <pre>
                  <code>
                    <span className={styles.cmt}># research a company and draft the outreach</span>
                    {"\n"}
                    <span className={styles.tok}>curl</span> -X POST \{"\n"}
                    {"  "}https://outly.onrender.com/api/v1/prospect \{"\n"}
                    {"  "}-H <span className={styles.str}>&quot;Authorization: Bearer outly_sk_…&quot;</span> \{"\n"}
                    {"  "}-H <span className={styles.str}>&quot;Content-Type: application/json&quot;</span> \{"\n"}
                    {"  "}-d <span className={styles.str}>{"'{"}</span>{"\n"}
                    {"    "}<span className={styles.str}>&quot;company&quot;: &quot;Razorpay&quot;,</span>{"\n"}
                    {"    "}<span className={styles.str}>&quot;industry&quot;: &quot;Fintech&quot;,</span>{"\n"}
                    {"    "}<span className={styles.str}>&quot;role&quot;: &quot;Senior Backend Engineer&quot;</span>{"\n"}
                    {"  "}<span className={styles.str}>{"}'"}</span>
                  </code>
                </pre>
              </div>
            </Rise>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- faq -- */}
      <section className={styles.sectionTight}>
        <div className={styles.shell}>
          <Rise className={styles.sectionHead}>
            <span className={styles.overline}>07 / Questions</span>
            <h2 className={styles.sectionTitle}>The things people ask first.</h2>
          </Rise>

          <div className={styles.faq}>
            {FAQ.map((item) => (
              <details key={item.q} className={styles.faqItem}>
                <summary>
                  {item.q}
                  <Plus className={styles.faqSign} size={18} strokeWidth={2} />
                </summary>
                <p className={styles.faqA}>{item.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- cta -- */}
      <section className={styles.cta}>
        <div className={styles.bandGlow} aria-hidden />
        <div className={styles.shell}>
          <Rise>
            <h2 className={styles.ctaTitle}>Your next message is already half written.</h2>
            <p className={styles.ctaSub}>
              Give Outly a company name or a resume, and watch the evidence trail come
              back with the email attached.
            </p>
            <div className={styles.ctaBtns}>
              <Link href={primaryHref} className={`${styles.btn} ${styles.btnLight} ${styles.btnLg}`}>
                {email ? "Open workspace" : "Create an account"}
                <ArrowRight size={17} strokeWidth={2.4} />
              </Link>
              {!email && (
                <Link href="/login" className={`${styles.btn} ${styles.btnOutlineLight} ${styles.btnLg}`}>
                  Sign in
                </Link>
              )}
            </div>
          </Rise>
        </div>
      </section>

      {/* ------------------------------------------------------- footer -- */}
      <footer className={styles.footer}>
        <div className={styles.shell}>
          <div className={styles.footerGrid}>
            <div>
              <Link href="/" className={styles.brand}>
                <OutlyMark size={30} className={styles.brandMark} />
                <span className={styles.brandName}>Outly</span>
              </Link>
              <p className={styles.footerTag}>
                An autonomous research agent for the people who still have to write the
                first message.
              </p>
            </div>

            <div>
              <div className={styles.footerHead}>Product</div>
              <div className={styles.footerCol}>
                <Link href="/prospecting" className={styles.footerLink}>Prospecting</Link>
                <Link href="/resume" className={styles.footerLink}>Resume prospecting</Link>
                <Link href="/jobs" className={styles.footerLink}>Job search</Link>
                <Link href="/drafts" className={styles.footerLink}>Drafts</Link>
                <Link href="/batch" className={styles.footerLink}>Batch upload</Link>
              </div>
            </div>

            <div>
              <div className={styles.footerHead}>Developers</div>
              <div className={styles.footerCol}>
                <Link href="/api-docs" className={styles.footerLink}>API documentation</Link>
                <Link href="/settings/api-keys" className={styles.footerLink}>API keys</Link>
              </div>
            </div>

            <div>
              <div className={styles.footerHead}>Account</div>
              <div className={styles.footerCol}>
                <Link href="/login" className={styles.footerLink}>Sign in</Link>
                <Link href="/login" className={styles.footerLink}>Create an account</Link>
              </div>
            </div>
          </div>

          <div className={styles.footerBottom}>
            <span>© {new Date().getFullYear()} Outly. All rights reserved.</span>
            <span>Built for people who send the first message.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/** Numbered pipeline list with a connecting rail, used inside both mode cards. */
function Flow({ items }: { items: string[] }) {
  return (
    <div className={styles.flow}>
      {items.map((text, i) => (
        <div key={text} className={styles.flowStep}>
          <span className={styles.flowRail}>
            <span className={styles.flowDot} />
            {i < items.length - 1 && <span className={styles.flowLine} />}
          </span>
          <span className={styles.flowText}>{text}</span>
        </div>
      ))}
    </div>
  );
}
