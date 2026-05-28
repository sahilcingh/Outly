#!/usr/bin/env python3
"""
B2B Prospecting Agent

Flow: Search -> Scrape -> Clean -> Chunk -> [Draft via Gemini] -> Save to SQLite

Usage:
    python main.py "Acme Corp"                         # full pipeline
    python main.py "Acme Corp" --no-draft              # search/scrape/chunk only
    python main.py "Acme Corp" --sequence              # include 3-touch follow-up
    python main.py "Acme Corp" --force                 # re-run even if already drafted
    python main.py --csv leads.csv                     # batch mode from CSV file
    python main.py --list                              # list all saved drafts
    python main.py --due-today                         # show approved touches due today
    python main.py --approve 1                         # approve draft #1
    python main.py --reject 1                          # reject draft #1
    python main.py --mark-sent 2                       # mark draft #2 as sent
    python main.py --send 1 --to prospect@example.com # send approved draft via SMTP
"""

import argparse
import concurrent.futures
import csv
import logging
import re
import sys
from pathlib import Path

from tools.search_tool import SearchResult, find_official_website
from tools.scrape_tool import scrape_with_socials
from tools.hiring_signal import find_hiring_signals
from tools.news_signal import find_recent_news
from tools.company_finder import find_companies_for_candidate
from llm.skills_extractor import extract_skills
from utils.text_cleaner import clean_text
from utils.chunker import chunk_text, Chunk
from llm.drafter import draft_email, PROMPT_VERSION
from llm.profiler import build_company_profile
from llm.role_analyzer import infer_role_and_contact
from llm.sequencer import generate_email_sequence
from tools.contact_extractor import find_contact
from storage.drafts import (
    company_already_drafted,
    get_draft,
    init_db,
    list_drafts,
    list_due_touches,
    save_company_profile,
    save_draft,
    save_outreach_touch,
    update_draft_status,
    update_touch_status,
)
from target_context import resolve_target_context

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contact title validator
# ---------------------------------------------------------------------------

def _is_valid_contact_title(title: str) -> bool:
    """
    Returns True only if the string looks like a real job title.
    Rejects scraped text snippets that the LLM or extractor mistakenly returns.
    """
    if not title:
        return False
    t = title.strip()
    # Too long to be a job title
    if len(t) > 70:
        return False
    # Em/en dashes indicate it's a sentence or scraped description, not a title
    if "—" in t or "–" in t:
        return False
    # More than 7 words is almost certainly not a job title
    if len(t.split()) > 7:
        return False
    # Contains sentence-ending punctuation — it's scraped prose
    if any(c in t for c in (".", ",", ";", "!")):
        return False
    return True


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def draft_passes_quality_gate(draft: dict) -> tuple[bool, list[str]]:
    """Hard gate only — missing fields or body too short to be useful."""
    reasons: list[str] = []

    subject = str(draft.get("subject", "")).strip()
    body = str(draft.get("body", "")).strip()
    rationale = str(draft.get("rationale", "")).strip()

    if not subject or not body or not rationale:
        reasons.append("missing required fields")

    word_count = len(re.findall(r"\b\w+\b", body))
    if word_count < 10:
        reasons.append(f"body too short ({word_count} words)")

    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# Official website resolver
# ---------------------------------------------------------------------------

def get_official_website(company_query: str, industry: str | None = None) -> list[SearchResult]:
    """Return a single-element list with the official website, or empty list."""
    if company_query.startswith("http://") or company_query.startswith("https://"):
        return [SearchResult(title="Direct URL", url=company_query, snippet="")]

    log.info("Finding official website for: '%s'", company_query)
    result = find_official_website(company_query, industry=industry)
    if result:
        log.info("Official site found: %s (score-based)", result.url)
        return [result]

    log.warning("Could not confidently identify an official website for '%s'.", company_query)
    return []


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    query: str,
    top_n: int = 3,
    run_drafter: bool = True,
    run_sequence: bool = False,
    industry: str | None = None,
    job_title: str | None = None,
    force: bool = False,
    progress_callback=None,
    user_id: int | None = None,
) -> list[tuple[SearchResult, list[Chunk], dict | None]]:
    """
    Execute Search -> Scrape -> Clean -> Chunk [-> Draft -> Save].

    Args:
        force: Skip duplicate guard and re-draft even if already in DB.
    """
    def emit(step: str, detail: str = "") -> None:
        if progress_callback:
            progress_callback(step, detail)

    init_db()
    ctx = resolve_target_context(industry, job_title)
    output: list[tuple[SearchResult, list[Chunk], dict | None]] = []

    emit("searching", f"Finding official website for '{query}'...")
    results = get_official_website(query, industry=ctx.industry)
    if not results:
        emit("error", f"No official website found for '{query}'.")
        log.error("No official website found for '%s'. Try passing the URL directly.", query)
        return []

    for result in results:
        draft_data = None
        try:
            emit("found", result.url)

            # --- Duplicate guard ---
            if run_drafter and not force and company_already_drafted(result.url):
                log.warning(
                    "Skipping '%s' — already drafted. Use --force to re-draft.", result.url
                )
                emit("duplicate", result.url)
                continue

            emit("scraping", f"Scraping {result.url}...")
            log.info("Scraping: %s", result.url)
            social_links: list[str] = []
            try:
                raw_text, social_links = scrape_with_socials(result.url)
            except Exception as scrape_e:
                log.warning("Scrape failed (%s).", scrape_e)
                raw_text = ""

            # Fallback chain for JS-heavy SPAs whose homepage returns almost no text
            if not raw_text or len(raw_text.strip()) < 50:
                log.warning("Homepage too sparse (%d chars) — trying subpages.", len((raw_text or "").strip()))
                _subpages = (
                    "/about", "/about-us", "/company", "/our-story",
                    "/who-we-are", "/blog", "/press", "/careers", "/docs",
                )
                for path in _subpages:
                    alt_url = result.url.rstrip("/") + path
                    try:
                        alt_text, alt_socials = scrape_with_socials(alt_url)
                        if alt_text and len(alt_text.strip()) >= 50:
                            raw_text = alt_text
                            social_links = social_links or alt_socials
                            log.info("Got content from fallback page: %s", alt_url)
                            break
                    except Exception:
                        continue

            # Last resort: use search snippet — fetch one if probe bypassed DuckDuckGo
            if not raw_text or len(raw_text.strip()) < 50:
                snippet = result.snippet
                if not snippet or len(snippet.strip()) < 20:
                    # Phase 1 (probe) skipped search — do a quick targeted query now
                    log.warning("No snippet available — fetching one via search.")
                    try:
                        from tools.search_tool import search as _ddg
                        for _sr in _ddg(f"{query} company product service", max_results=5):
                            if _sr.snippet and len(_sr.snippet.strip()) >= 20:
                                snippet = f"{_sr.title}. {_sr.snippet}"
                                break
                    except Exception:
                        pass

                if snippet and len(snippet.strip()) >= 20:
                    raw_text = f"{result.title}. {snippet}"
                    log.warning("Using search snippet as last resort (%d chars).", len(raw_text))
                else:
                    log.warning("No usable text found for '%s' — skipping.", query)
                    continue

            if social_links:
                log.info("Found %d social links.", len(social_links))
                social_section = (
                    "\n--- Company Social Media Links ---\n"
                    + "\n".join(f"- {sl}" for sl in social_links)
                    + "\n"
                )
                raw_text = raw_text + social_section

            clean = clean_text(raw_text)
            if not clean:
                continue

            chunks = chunk_text(clean, chunk_size=512, overlap=64)

            if run_drafter and chunks:
                # Fetch live signals in parallel (threads) — non-blocking to the rest of pipeline
                emit("signals", "Fetching hiring signals and recent news...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    future_hiring = pool.submit(find_hiring_signals, result.url, result.title)
                    future_news = pool.submit(find_recent_news, result.title)
                    try:
                        ctx.hiring_signals = future_hiring.result(timeout=10)
                    except Exception as e:
                        log.warning("Hiring signal fetch failed: %s", e)
                        ctx.hiring_signals = []
                    try:
                        ctx.news_signals = future_news.result(timeout=10)
                    except Exception as e:
                        log.warning("News signal fetch failed: %s", e)
                        ctx.news_signals = []

                if ctx.hiring_signals:
                    log.info("Active roles found: %s", ctx.hiring_signals[:3])
                if ctx.news_signals:
                    log.info("Recent news: %s", [n["title"] for n in ctx.news_signals])

                # Step A: always run role analysis to populate both role and contact_title.
                # Only override role_to_offer if the user didn't provide one explicitly.
                log.info("Analyzing company content for role and contact...")
                try:
                    analysis = infer_role_and_contact(clean)
                except Exception as analysis_e:
                    log.warning("Role analysis failed (%s) — using fallbacks.", analysis_e)
                    analysis = None
                if analysis:
                    if not ctx.role_to_offer:
                        ctx.role_to_offer = analysis.get("role_to_offer", "")
                    inferred_title = analysis.get("contact_title", "")
                    if not ctx.contact_title and _is_valid_contact_title(inferred_title):
                        ctx.contact_title = inferred_title
                    elif inferred_title and not _is_valid_contact_title(inferred_title):
                        log.warning("Rejected bad contact_title from LLM: %r", inferred_title)
                    log.info("Role: %s | Contact title: %s", ctx.role_to_offer, ctx.contact_title)

                # Hard fallbacks — pipeline never proceeds with empty role or contact
                if not ctx.role_to_offer:
                    ctx.role_to_offer = "Senior Software Engineer"
                    log.warning("Role unknown — defaulting to: %s", ctx.role_to_offer)
                if not ctx.contact_title:
                    ctx.contact_title = "Head of Talent Acquisition"
                    log.warning("Contact title unknown — defaulting to: %s", ctx.contact_title)

                # Step B: find the actual contact person on the company website
                if not ctx.contact_name:
                    log.info("Searching for contact person on company website...")
                    try:
                        contact = find_contact(result.url)
                    except Exception as contact_e:
                        log.warning("Contact search failed (%s).", contact_e)
                        contact = None
                    if contact:
                        ctx.contact_name = contact.get("name")
                        extracted_title = contact.get("title", "")
                        if _is_valid_contact_title(extracted_title):
                            ctx.contact_title = extracted_title
                        elif extracted_title:
                            log.warning("Rejected bad contact_title from extractor: %r", extracted_title)
                        ctx.contact_email = contact.get("email")

                log.info("Drafting email → TO: %s (%s) | OFFERING: %s",
                         ctx.contact_name or "unknown", ctx.contact_title, ctx.role_to_offer)
                emit("drafting", f"Writing personalized email for {result.title}...")
                draft_data = draft_email(clean, context=ctx)

                if draft_data:
                    passed, reasons = draft_passes_quality_gate(draft_data)
                    if not passed:
                        log.warning("Draft quality warning: %s", ", ".join(reasons))
                    if all(k in draft_data for k in ("subject", "body", "rationale")):
                        save_draft(
                            company_name=result.title[:200],
                            company_url=result.url,
                            subject=draft_data["subject"],
                            body=draft_data["body"],
                            rationale=draft_data["rationale"],
                            prompt_version=PROMPT_VERSION,
                            user_id=user_id,
                        )
                        log.info("Draft saved [%s]: %s", PROMPT_VERSION, draft_data["subject"][:60])
                        # Attach discovered context for callers (web UI)
                        draft_data["role_to_offer"] = ctx.role_to_offer
                        draft_data["contact_name"] = ctx.contact_name
                        draft_data["contact_title"] = ctx.contact_title
                        draft_data["contact_email"] = ctx.contact_email
                        draft_data["hiring_signals"] = ctx.hiring_signals
                        draft_data["news_signals"] = ctx.news_signals
                        draft_data["company_name"] = result.title

            if run_sequence and chunks:
                log.info("Generating 3-touch follow-up sequence...")
                profile = build_company_profile(clean, context=ctx)
                if isinstance(profile, dict) and profile:
                    save_company_profile(result.title[:200], result.url, profile)
                    seq = generate_email_sequence(profile, context=ctx)
                    touches = seq.get("touches") if isinstance(seq, dict) else None
                    if isinstance(touches, list):
                        for i, t in enumerate(touches):
                            if not isinstance(t, dict):
                                continue
                            if str(t.get("channel", "")).lower() != "email":
                                continue
                            if not all(k in t for k in ("touch_index", "subject", "body", "rationale")):
                                continue
                            # Space touches 3 days apart from today
                            from datetime import date, timedelta
                            send_after = (date.today() + timedelta(days=3 * (i + 1))).isoformat()
                            save_outreach_touch(
                                company_name=result.title[:200],
                                company_url=result.url,
                                touch_index=int(t["touch_index"]),
                                channel="email",
                                subject=str(t["subject"])[:200],
                                body=str(t["body"]),
                                rationale=str(t["rationale"]),
                                send_after=send_after,
                            )

            output.append((result, chunks, draft_data))

            if (run_drafter and draft_data) or (not run_drafter and chunks):
                log.info("Pipeline complete for '%s'.", query)
                break

        except Exception as e:
            log.error("Error processing %s: %s", result.url, e)
            continue

    return output


# ---------------------------------------------------------------------------
# Resume-based pipeline
# ---------------------------------------------------------------------------

def run_resume_pipeline(
    resume_text: str,
    max_companies: int = 6,
    industry: str | None = None,
    user_id: int | None = None,
    progress_callback=None,
) -> list[dict]:
    """
    Reverse pipeline: given a candidate's resume text, find matching companies
    and generate a personalized outreach draft for each one.

    Returns a list of result dicts, each containing company + draft info.
    """
    def emit(step: str, detail: str = "") -> None:
        if progress_callback:
            progress_callback(step, detail)

    init_db()
    results = []

    # Step 1: Extract candidate profile from resume
    emit("analyzing_resume", "Extracting skills and role from resume...")
    profile = extract_skills(resume_text)
    if not profile:
        emit("error", "Could not extract skills from resume. Try pasting the text directly.")
        return []

    role_title = profile.get("role_title", "Software Engineer")
    skills = profile.get("skills", [])
    search_queries = profile.get("search_queries", [])
    candidate_industry = industry or (profile.get("industries", ["Technology"])[0] if profile.get("industries") else "Technology")
    summary = profile.get("summary", "")

    log.info("Candidate: %s | Skills: %s", role_title, skills[:5])
    emit("profile_ready", f"Role: {role_title} | Skills: {', '.join(skills[:5])}")

    # Step 2: Find matching companies
    emit("finding_companies", f"Searching for companies that hire {role_title}...")
    companies = find_companies_for_candidate(
        search_queries=search_queries,
        skills=skills,
        max_companies=max_companies,
    )
    if not companies:
        emit("error", "No matching companies found. Try adjusting the resume or industry.")
        return []

    emit("companies_found", f"Found {len(companies)} matching companies")
    log.info("Companies found: %s", [c["name"] for c in companies])

    # Step 3: For each company, run the prospecting pipeline
    for i, company in enumerate(companies):
        company_name = company["name"]
        company_url = company["url"]
        emit("prospecting", f"[{i+1}/{len(companies)}] Researching {company_name}...")

        try:
            output = run_pipeline(
                query=company_url,
                run_drafter=True,
                run_sequence=False,
                industry=candidate_industry,
                job_title=role_title,
                force=False,
                user_id=user_id,
                progress_callback=None,  # Suppress sub-pipeline events
            )
            for result, chunks, draft_data in output:
                if draft_data:
                    draft_data["company_name"] = result.title or company_name
                    draft_data["company_url"] = result.url
                    draft_data["candidate_role"] = role_title
                    draft_data["candidate_skills"] = skills
                    results.append(draft_data)
                    log.info("Draft ready for %s", company_name)
                    break
        except Exception as e:
            log.warning("Pipeline failed for %s: %s", company_name, e)
            continue

    emit("done", f"Generated {len(results)} drafts across {len(companies)} companies")
    return results


# ---------------------------------------------------------------------------
# Batch CSV
# ---------------------------------------------------------------------------

def run_batch_csv(csv_path: str, run_sequence: bool = False, force: bool = False) -> None:
    """Read a CSV file and run the pipeline for each row.

    CSV columns: company_name (required), industry (optional), job_title (optional)
    """
    path = Path(csv_path)
    if not path.exists():
        log.error("CSV file not found: %s", csv_path)
        sys.exit(1)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info("Batch mode: %d companies from %s", len(rows), csv_path)
    for i, row in enumerate(rows, 1):
        company = (row.get("company_name") or row.get("company") or "").strip()
        if not company:
            log.warning("Row %d: empty company_name — skipping.", i)
            continue
        industry = (row.get("industry") or "").strip() or None
        job_title = (row.get("job_title") or "").strip() or None
        log.info("[%d/%d] Processing: %s", i, len(rows), company)
        run_pipeline(
            company,
            run_drafter=True,
            run_sequence=run_sequence,
            industry=industry,
            job_title=job_title,
            force=force,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="B2B Prospecting Agent")
    parser.add_argument("query", nargs="?", help="Company name or URL")
    parser.add_argument("--top", type=int, default=3, help="Max URLs to process (default 3)")
    parser.add_argument("--no-draft", action="store_true", help="Skip LLM draft and save")
    parser.add_argument("--sequence", action="store_true", help="Generate 3-touch follow-up sequence")
    parser.add_argument("--force", action="store_true", help="Re-run even if company already drafted")
    parser.add_argument("--industry", default=None, help="Industry framing for prompts")
    parser.add_argument("--job-title", dest="job_title", default=None, help="Target recipient job title")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print text chunks")

    # Batch
    parser.add_argument("--csv", dest="csv_path", default=None, metavar="FILE",
                        help="Batch mode: path to CSV with columns: company_name, industry, job_title")

    # Draft management
    parser.add_argument("--list", action="store_true", help="List saved drafts and exit")
    parser.add_argument("--approve", type=int, metavar="ID", help="Approve draft by id")
    parser.add_argument("--reject", type=int, metavar="ID", help="Reject draft by id")
    parser.add_argument("--mark-sent", type=int, metavar="ID", help="Mark draft as sent by id")

    # Scheduling
    parser.add_argument("--due-today", action="store_true",
                        help="List approved outreach touches due today or earlier")

    # Send via SMTP
    parser.add_argument("--send", type=int, metavar="ID",
                        help="Send an approved draft by id via SMTP")
    parser.add_argument("--to", dest="to_email", default=None, metavar="EMAIL",
                        help="Recipient email address (required with --send)")

    args = parser.parse_args()

    # --- Status updates ---
    if args.approve is not None:
        ok = update_draft_status(args.approve, "approved")
        print("Approved." if ok else "Draft not found.")
        return

    if args.reject is not None:
        ok = update_draft_status(args.reject, "rejected")
        print("Rejected." if ok else "Draft not found.")
        return

    if args.mark_sent is not None:
        ok = update_draft_status(args.mark_sent, "sent")
        print("Marked as sent." if ok else "Draft not found.")
        return

    # --- List drafts ---
    if args.list:
        init_db()
        drafts = list_drafts()
        if not drafts:
            print("No drafts saved yet.")
            return
        for d in drafts:
            subj = d.subject[:60] + "..." if len(d.subject) > 60 else d.subject
            print(f"[{d.id}] {d.company_name} | {d.status} | pv={d.prompt_version} | {d.created_at}")
            print(f"  Subject: {subj}")
        return

    # --- Due today ---
    if args.due_today:
        init_db()
        touches = list_due_touches()
        if not touches:
            print("No approved touches due today.")
            return
        for t in touches:
            print(f"[{t.id}] Touch {t.touch_index} | {t.company_name} | due {t.send_after} | {t.status}")
            print(f"  Subject: {t.subject[:70]}")
        return

    # --- Send via SMTP ---
    if args.send is not None:
        if not args.to_email:
            parser.error("--to EMAIL is required with --send")
        from tools.email_sender import send_email
        init_db()
        draft = get_draft(args.send)
        if not draft:
            print(f"Draft #{args.send} not found.")
            sys.exit(1)
        if draft.status not in ("approved", "draft"):
            print(f"Draft #{args.send} has status '{draft.status}' — only 'approved' or 'draft' can be sent.")
            sys.exit(1)
        log.info("Sending draft #%d to %s ...", args.send, args.to_email)
        send_email(args.to_email, draft.subject, draft.body)
        update_draft_status(args.send, "sent")
        print(f"Sent draft #{args.send} to {args.to_email} and marked as sent.")
        return

    # --- Batch CSV ---
    if args.csv_path:
        run_batch_csv(args.csv_path, run_sequence=bool(args.sequence), force=bool(args.force))
        return

    # --- Single company ---
    if not args.query:
        parser.error("query required unless using --list / --approve / --reject / --mark-sent / --due-today / --send / --csv")

    ctx = resolve_target_context(args.industry, args.job_title)
    log.info("Query: %s | industry: %s | job_title: %s", args.query, ctx.industry, ctx.job_title)
    log.info("-" * 60)

    pipeline_output = run_pipeline(
        args.query,
        top_n=args.top,
        run_drafter=not args.no_draft,
        run_sequence=bool(args.sequence),
        industry=ctx.industry,
        job_title=ctx.job_title,
        force=bool(args.force),
    )

    for result, chunks, draft in pipeline_output:
        print(f"\n{result.title}")
        print(f"  URL: {result.url}")
        print(f"  Chunks: {len(chunks)}")
        if draft:
            print(f"  Subject: {draft.get('subject', '')[:70]}")
        if args.verbose and chunks:
            for c in chunks:
                preview = c.text[:80] + "..." if len(c.text) > 80 else c.text
                safe_preview = preview.encode("ascii", errors="replace").decode()
                print(f"    [{c.index}] {safe_preview}")


if __name__ == "__main__":
    main()
