# Session Summary — 2026-08-22

Scope: pulled the new Next.js decoupled frontend, fixed breaks in it, fixed a live
LLM outage, and scoped a Supabase migration. Companion log to `status.txt`.

## Completed

- [x] **Pulled latest `Outly` code from GitHub** — fast-forwarded `main` from
      `f61abab` to `b217544` (`outly-client/` Next.js frontend + `web.py` changes).
- [x] **Ran the app locally** — FastAPI backend (`127.0.0.1:8000`) + Next.js
      frontend (`127.0.0.1:3001`), verified both serve.
- [x] **Fixed: Drafts page always showed "No Drafts Found"** — `GET /drafts`
      only ever returned server-rendered HTML, not JSON. Added `GET /api/drafts`
      JSON endpoint (`web.py`); old HTML route left untouched.
- [x] **Fixed: Jobs page "Job Queue" panel was a dead placeholder** — added
      `GET /api/jobs/queue` JSON endpoint and wired `jobs/page.tsx` to actually
      fetch and render real queued jobs.
- [x] **Fixed: auth was fully bypassed** — `_is_authenticated()` was hardcoded
      `return True` (introduced in the same migration commit). Reverted to real
      session checking (`storage/users.py` session model).
- [x] **Fixed: OpenText / enterprise-ATS jobs had no direct apply link** —
      `tools/job_search.py` now prefers jobspy's `job_url_direct` over the
      LinkedIn/Indeed listing page, and `_detect_apply()` recognizes Workday,
      SAP SuccessFactors, and Taleo (previously only Greenhouse/Lever/Workable/
      Ashby/Rippling/SmartRecruiters/Jobvite/iCIMS).
- [x] **Removed cross-origin cookie plumbing** — added a Next.js rewrite proxy
      (`next.config.ts`: `/backend/:path*` → FastAPI) so the browser only talks
      to one origin. Dropped `credentials: "include"` / `withCredentials` from
      every fetch/EventSource call in the frontend.
- [x] **Built the missing login/register UI** — `src/app/login/page.tsx`,
      `auth-context.tsx` (`AuthProvider`, redirects unauthenticated visits to
      `/login`), `UserMenu.tsx` (shows email + logout in the nav).
- [x] **Fixed a live outage: Groq deprecated `llama-3.3-70b-versatile`** — every
      LLM call (role inference, contact discovery, email drafting, job scoring)
      was 404ing with `model_not_found`, surfacing to users as a generic
      "No draft generated" error on any company search. Verified the current
      model catalog against the live Groq API and switched the default to
      `openai/gpt-oss-120b` in `config.py`. Verified end-to-end with a real
      "Meta" search — both LLM calls now return 200 and a draft saves.
- [x] Reviewed and rewrote the resume bullet points for the lead-research
      platform project (unrelated to the codebase — separate one-off ask).
- [x] Scoped a Supabase integration plan (resumes, drafts, session/job history)
      and suggested additions — **discussion only, nothing implemented yet.**

## Known issues / not yet fixed

- [ ] **Scheduler is single-tenant.** `scheduler/job_runner.py` and its `.env`
      knobs (`JOB_LOCATIONS`, `MIN_MATCH_SCORE`, `CANDIDATE_LEVEL`,
      `SENIORITY_STRICT`, `JOB_EXTRA_KEYWORDS`, `SCHEDULER_USER_ID`) are global,
      driving one hardcoded user. Needs to become per-user once real multi-user
      data (Supabase) lands, or the auto-search feature only ever works for one
      account.
- [ ] **Notification targets are global, not per-user** — `TELEGRAM_BOT_TOKEN` /
      `TELEGRAM_CHAT_ID` and the Gmail sender creds are single env values.
- [ ] **New login UI only smoke-tested via curl through the proxy** — the
      register → session-cookie → protected-page flow was verified at the HTTP
      level, not click-through in a real browser. Worth a manual pass.
- [ ] **Two throwaway test accounts left in the live Neon DB**:
      `testuser_verify2@example.com`, `proxytest@example.com`. Offered to
      delete, not yet actioned — confirm before removing.
- [ ] `duckduckgo_search` is deprecated in favor of `ddgs` (warning seen in
      logs during pipeline runs) — cosmetic/maintenance, not breaking anything
      yet.
- [ ] `status.txt`'s "known limitations" note about SQLite resetting on
      redeploy is stale — the app now runs on Postgres/Neon via `DATABASE_URL`,
      not SQLite. Worth updating that log entry.

## Next up (pending your direction)

- [ ] **Supabase schema design** — users/resumes/drafts/job_history tables +
      Row Level Security policies, covering the three things you named
      (single latest resume per user, drafts, session-wise job-suggestion
      history) plus the additions discussed:
      - Per-user search preferences (replacing the global `.env` knobs above)
      - Parsed resume fields (skills/experience/seniority) alongside raw text
      - Supabase Storage for the actual resume file, not just parsed text
      - Supabase Auth (replacing the current homegrown session/password system)
      - Realtime subscriptions on drafts/jobs tables for live dashboard updates
      - Applied-jobs funnel analytics (drafted → approved → sent)
- [ ] Fix the scheduler multi-tenancy gap (see above) — likely needs doing
      alongside or right after the Supabase migration.
