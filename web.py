import asyncio
import csv
import io
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import get_secret_key, get_render_url, get_telegram_token, get_scheduler_user_id
from main import run_pipeline, run_batch_csv, run_resume_pipeline
from tools.resume_parser import parse_resume
from storage.users import create_user, verify_login, init_users_table
from storage.api_keys import create_api_key, get_user_by_api_key, list_api_keys, revoke_api_key
from storage.drafts import (
    get_draft,
    init_db,
    list_drafts,
    save_draft,
    update_draft_status,
)
from storage.jobs import (
    init_jobs_table,
    save_job_application,
    list_job_applications,
    get_job_application,
    update_job_status,
    update_cover_letter,
    get_existing_job_urls,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APScheduler
# ---------------------------------------------------------------------------

_scheduler = None

def _start_scheduler() -> None:
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        from scheduler.job_runner import run_scheduled_search

        IST = pytz.timezone("Asia/Kolkata")
        _scheduler = BackgroundScheduler(timezone=IST)
        _scheduler.add_job(
            run_scheduled_search,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=IST),
            id="morning_search",
        )
        _scheduler.add_job(
            run_scheduled_search,
            CronTrigger(day_of_week="mon-fri", hour=14, minute=30, timezone=IST),
            id="afternoon_search",
        )
        _scheduler.start()
        log.info("APScheduler started (09:30 + 14:30 IST, weekdays)")
    except Exception as e:
        log.warning("APScheduler not started: %s", e)


def _register_telegram_webhook() -> None:
    render_url = get_render_url()
    if not render_url or not get_telegram_token():
        log.info("Telegram webhook not registered (RENDER_EXTERNAL_URL or TELEGRAM_BOT_TOKEN missing)")
        return
    try:
        from tools.telegram_bot import register_webhook
        webhook_url = f"{render_url.rstrip('/')}/telegram/webhook"
        register_webhook(webhook_url)
    except Exception as e:
        log.warning("Telegram webhook registration failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_scheduler()
    _register_telegram_webhook()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="B2B Prospecting Agent", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_secret_key(), max_age=86400 * 7)


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url)
    return HTMLResponse(
        content=f"<h2>Internal Server Error</h2><pre>{type(exc).__name__}: {exc}</pre>"
                f"<p><a href='/'>← Back to home</a></p>",
        status_code=500,
    )

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _current_user_id(request: Request) -> int | None:
    return request.session.get("user_id")


def _current_user_email(request: Request) -> str | None:
    return request.session.get("user_email")


def _is_authenticated(request: Request) -> bool:
    return _current_user_id(request) is not None


def _require_auth(request: Request) -> RedirectResponse | None:
    if not _is_authenticated(request):
        return RedirectResponse(url=f"/login?next={request.url}", status_code=303)
    return None

os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if _is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="register.html", context={"error": None, "email": ""}
    )


@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    email = email.strip().lower()
    if len(password) < 8:
        return templates.TemplateResponse(request=request, name="register.html",
            context={"error": "Password must be at least 8 characters.", "email": email})
    if password != confirm_password:
        return templates.TemplateResponse(request=request, name="register.html",
            context={"error": "Passwords do not match.", "email": email})

    try:
        init_users_table()
    except Exception as e:
        log.exception("init_users_table failed")
        return templates.TemplateResponse(request=request, name="register.html",
            context={"error": f"Database error: {e}", "email": email})

    user = create_user(email, password)
    if not user:
        return templates.TemplateResponse(request=request, name="register.html",
            context={"error": "An account with this email already exists.", "email": email})

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    return RedirectResponse(url="/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    if _is_authenticated(request):
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None, "next": next, "email": ""}
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    email = email.strip().lower()
    user = verify_login(email, password)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html",
            context={"error": "Invalid email or password.", "next": next, "email": email})

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    return RedirectResponse(url=next or "/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# ---------------------------------------------------------------------------
# In-memory job store for SSE progress streaming
# ---------------------------------------------------------------------------
# job_id → {"events": list[dict], "done": bool, "result": dict|None, "error": str|None}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_STEP_LABELS = {
    "searching":  "🔍 Searching for official website...",
    "found":      "✅ Website found",
    "duplicate":  "⚠️  Already drafted — use --force to re-run",
    "cached":     "📦 Using existing draft from database",
    "scraping":   "🌐 Scraping website content...",
    "signals":    "📡 Fetching hiring signals & recent news...",
    "analyzing":  "🧠 Analyzing company tech stack & role fit...",
    "contact":    "👤 Looking for contact person...",
    "drafting":   "✍️  Writing personalized email...",
    "done":       "🎉 Draft ready!",
    "error":      "❌ Error",
}


def _push(job_id: str, step: str, detail: str = "") -> None:
    label = _STEP_LABELS.get(step, step)
    event = {"step": step, "label": label, "detail": detail}
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["events"].append(event)


def _run_pipeline_thread(
    job_id: str,
    query: str,
    industry: str | None,
    job_title: str | None,
    user_id: int | None = None,
) -> None:
    def progress(step: str, detail: str = "") -> None:
        _push(job_id, step, detail)

    try:
        pipeline_output = run_pipeline(
            query=query,
            industry=industry,
            job_title=job_title,
            run_drafter=True,
            run_sequence=False,
            progress_callback=progress,
            user_id=user_id,
        )

        result = None
        url = None
        for res, chunks, d in pipeline_output:
            if d:
                result = d
                url = res.url
                break

        with _jobs_lock:
            _jobs[job_id]["result"] = result
            _jobs[job_id]["url"] = url
            _jobs[job_id]["done"] = True

        if result:
            _push(job_id, "done", "Draft ready!")
        else:
            _push(job_id, "error",
                  "No draft generated. Company may already be drafted, or not enough data found.")

    except Exception as e:
        err_str = str(e)
        if any(k in err_str for k in ("RESOURCE_EXHAUSTED", "429", "quota")):
            msg = "Gemini API quota exceeded. Please try again later."
        else:
            log.exception("Pipeline error for job %s", job_id)
            msg = err_str
        with _jobs_lock:
            _jobs[job_id]["error"] = msg
            _jobs[job_id]["done"] = True
        _push(job_id, "error", msg)


# ---------------------------------------------------------------------------
# Home — single prospect form
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, job_id: str = None):
    if (r := _require_auth(request)):
        return r
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"result": None, "error": None, "job_id": job_id},
    )


@app.post("/", response_class=HTMLResponse)
async def run_agent(
    request: Request,
    query: str = Form(...),
    industry: str = Form(None),
    job_title: str = Form(None),
):
    if (r := _require_auth(request)):
        return r
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"events": [], "done": False, "result": None, "url": None, "error": None}

    threading.Thread(
        target=_run_pipeline_thread,
        args=(job_id, query, industry or None, job_title or None, _current_user_id(request)),
        daemon=True,
    ).start()

    # PRG: redirect to GET so page reload doesn't resubmit the form
    return RedirectResponse(url=f"/?job_id={job_id}", status_code=303)


# ---------------------------------------------------------------------------
# SSE — stream pipeline progress events to the browser
# ---------------------------------------------------------------------------

@app.get("/stream/{job_id}")
async def stream_events(request: Request, job_id: str):
    if not _is_authenticated(request):
        return StreamingResponse(
            iter([f"data: {json.dumps({'step': 'error', 'label': '❌ Not authenticated', 'detail': ''})}\n\n"]),
            media_type="text/event-stream",
        )
    async def generator():
        # If job is already done (e.g. page reload), send everything immediately
        with _jobs_lock:
            job = _jobs.get(job_id)
        if not job:
            yield f"data: {json.dumps({'step': 'error', 'label': '❌ Job not found', 'detail': ''})}\n\n"
            return
        if job["done"]:
            for event in job["events"]:
                yield f"data: {json.dumps(event)}\n\n"
            payload = {"step": "__result__", "result": job["result"], "url": job.get("url")}
            yield f"data: {json.dumps(payload)}\n\n"
            return

        # Job still running — stream events as they arrive
        last_sent = 0
        max_wait = 600
        waited = 0
        last_ping = 0

        while waited < max_wait:
            with _jobs_lock:
                job = _jobs.get(job_id)

            if not job:
                yield f"data: {json.dumps({'step': 'error', 'label': '❌ Job not found', 'detail': ''})}\n\n"
                return

            events = job["events"]
            new_events_sent = False
            while last_sent < len(events):
                yield f"data: {json.dumps(events[last_sent])}\n\n"
                last_sent += 1
                new_events_sent = True

            if job["done"]:
                payload = {"step": "__result__", "result": job["result"], "url": job.get("url")}
                yield f"data: {json.dumps(payload)}\n\n"
                return

            # Keepalive every 15s to prevent Render proxy timeout
            if not new_events_sent and (waited - last_ping) >= 15:
                yield ": keepalive\n\n"
                last_ping = waited

            await asyncio.sleep(0.5)
            waited += 0.5

        yield f"data: {json.dumps({'step': 'error', 'label': '❌ Timeout', 'detail': 'Pipeline took too long.'})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Draft inline edit — save user-edited subject/body
# ---------------------------------------------------------------------------

@app.post("/draft/save", response_class=HTMLResponse)
async def save_edited_draft(
    request: Request,
    company_name: str = Form(...),
    company_url: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    rationale: str = Form(""),
):
    if (r := _require_auth(request)):
        return r
    try:
        from llm.drafter import PROMPT_VERSION
        save_draft(
            company_name=company_name[:200],
            company_url=company_url,
            subject=subject,
            body=body,
            rationale=rationale or "Manually edited draft",
            prompt_version=PROMPT_VERSION,
            user_id=_current_user_id(request),
        )
        return RedirectResponse(url="/drafts", status_code=303)
    except Exception as e:
        log.exception("Save edited draft error")
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"result": None, "error": str(e), "job_id": None},
        )


# ---------------------------------------------------------------------------
# Resume-based prospecting
# ---------------------------------------------------------------------------

_RESUME_STEP_LABELS = {
    "analyzing_resume":    "🔍 Extracting skills from resume...",
    "profile_ready":       "✅ Candidate profile extracted",
    "finding_companies":   "🏢 Finding matching companies via AI...",
    "verifying_companies": "🔗 Verifying company websites...",
    "companies_found":     "✅ Companies verified",
    "prospecting":         "✍️  Researching & drafting...",
    "done":                "🎉 All drafts ready!",
    "error":               "❌ Error",
}


def _run_resume_thread(
    job_id: str,
    resume_text: str,
    industry: str | None,
    max_companies: int,
    user_id: int | None,
) -> None:
    def progress(step: str, detail: str = "") -> None:
        label = _RESUME_STEP_LABELS.get(step, step)
        event = {"step": step, "label": label, "detail": detail}
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["events"].append(event)

    try:
        results = run_resume_pipeline(
            resume_text=resume_text,
            max_companies=max_companies,
            industry=industry or None,
            user_id=user_id,
            progress_callback=progress,
        )
        with _jobs_lock:
            _jobs[job_id]["result"] = results
            _jobs[job_id]["done"] = True
        progress("done", f"{len(results)} drafts generated")
    except Exception as e:
        log.exception("Resume pipeline error for job %s", job_id)
        with _jobs_lock:
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["done"] = True
        progress("error", str(e))


@app.get("/resume", response_class=HTMLResponse)
async def resume_page(request: Request, job_id: str = None):
    if (r := _require_auth(request)):
        return r
    return templates.TemplateResponse(
        request=request, name="resume_prospect.html",
        context={"job_id": job_id, "error": None},
    )


@app.post("/resume", response_class=HTMLResponse)
async def resume_submit(
    request: Request,
    resume_file: UploadFile = File(None),
    resume_text: str = Form(""),
    industry: str = Form(""),
    max_companies: int = Form(6),
):
    if (r := _require_auth(request)):
        return r

    text = ""
    if resume_file and resume_file.filename:
        raw = await resume_file.read()
        text = parse_resume(raw, resume_file.filename)
    if not text and resume_text.strip():
        text = resume_text.strip()
    if not text:
        return templates.TemplateResponse(
            request=request, name="resume_prospect.html",
            context={"job_id": None, "error": "Please upload a PDF or paste your resume text."},
        )

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"events": [], "done": False, "result": None, "url": None, "error": None}

    threading.Thread(
        target=_run_resume_thread,
        args=(job_id, text, industry or None, min(max(max_companies, 1), 10), _current_user_id(request)),
        daemon=True,
    ).start()

    # PRG: redirect to GET so page reload doesn't resubmit the form
    return RedirectResponse(url=f"/resume?job_id={job_id}", status_code=303)


# ---------------------------------------------------------------------------
# Batch upload — CSV file
# ---------------------------------------------------------------------------

@app.get("/batch", response_class=HTMLResponse)
async def batch_form(request: Request):
    if (r := _require_auth(request)):
        return r
    return templates.TemplateResponse(request=request, name="batch.html", context={"message": None, "error": None})


@app.post("/batch", response_class=HTMLResponse)
async def batch_upload(request: Request, file: UploadFile = File(...)):
    if (r := _require_auth(request)):
        return r
    try:
        content = await file.read()
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

        if not rows:
            return templates.TemplateResponse(
                request=request,
                name="batch.html",
                context={"message": None, "error": "CSV file is empty or has no valid rows."},
            )

        processed = 0
        for row in rows:
            company = (row.get("company_name") or row.get("company") or "").strip()
            if not company:
                continue
            industry = (row.get("industry") or "").strip() or None
            job_title = (row.get("job_title") or "").strip() or None
            run_pipeline(company, run_drafter=True, run_sequence=False,
                         industry=industry, job_title=job_title)
            processed += 1

        return templates.TemplateResponse(
            request=request,
            name="batch.html",
            context={"message": f"Processed {processed} companies. Check the Drafts page for results.", "error": None},
        )

    except Exception as e:
        log.exception("Batch upload error")
        return templates.TemplateResponse(
            request=request, name="batch.html", context={"message": None, "error": str(e)}
        )


# ---------------------------------------------------------------------------
# Drafts review UI
# ---------------------------------------------------------------------------

@app.get("/drafts", response_class=HTMLResponse)
async def drafts_page(request: Request, status: str = ""):
    if (r := _require_auth(request)):
        return r
    init_db()
    filter_status = status if status in ("draft", "approved", "sent", "rejected") else None
    drafts = list_drafts(status=filter_status, user_id=_current_user_id(request))
    return templates.TemplateResponse(
        request=request,
        name="drafts.html",
        context={"drafts": drafts, "filter_status": filter_status or "all"},
    )


@app.get("/drafts/{draft_id}", response_class=HTMLResponse)
async def draft_detail(request: Request, draft_id: int):
    if (r := _require_auth(request)):
        return r
    init_db()
    draft = get_draft(draft_id)
    if not draft:
        return HTMLResponse(content="Draft not found.", status_code=404)
    return templates.TemplateResponse(request=request, name="draft_detail.html", context={"draft": draft})


@app.post("/drafts/{draft_id}/approve")
async def approve_draft(request: Request, draft_id: int):
    if (r := _require_auth(request)):
        return r
    update_draft_status(draft_id, "approved")
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/{draft_id}/reject")
async def reject_draft(request: Request, draft_id: int):
    if (r := _require_auth(request)):
        return r
    update_draft_status(draft_id, "rejected")
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/{draft_id}/sent")
async def mark_sent(request: Request, draft_id: int):
    if (r := _require_auth(request)):
        return r
    update_draft_status(draft_id, "sent")
    return RedirectResponse(url="/drafts", status_code=303)


# ---------------------------------------------------------------------------
# API Key management UI
# ---------------------------------------------------------------------------

@app.get("/settings/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request):
    if (r := _require_auth(request)):
        return r
    user_id = _current_user_id(request)
    keys = list_api_keys(user_id)
    return templates.TemplateResponse(
        request=request, name="api_keys.html",
        context={"keys": keys, "new_key": None, "error": None},
    )


@app.post("/settings/api-keys", response_class=HTMLResponse)
async def create_key(request: Request, key_name: str = Form(...)):
    if (r := _require_auth(request)):
        return r
    user_id = _current_user_id(request)
    full_key, api_key = create_api_key(user_id, key_name.strip() or "My API Key")
    keys = list_api_keys(user_id)
    return templates.TemplateResponse(
        request=request, name="api_keys.html",
        context={"keys": keys, "new_key": full_key, "error": None},
    )


@app.post("/settings/api-keys/{key_id}/revoke")
async def revoke_key(request: Request, key_id: int):
    if (r := _require_auth(request)):
        return r
    revoke_api_key(key_id, _current_user_id(request))
    return RedirectResponse(url="/settings/api-keys", status_code=303)


# ---------------------------------------------------------------------------
# REST API — v1
# ---------------------------------------------------------------------------

def _api_auth(request: Request) -> dict | None:
    """Validate Bearer token from Authorization header. Returns user row or None."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:].strip()
        return get_user_by_api_key(key)
    # Also accept X-API-Key header
    key = request.headers.get("X-API-Key", "").strip()
    if key:
        return get_user_by_api_key(key)
    return None


def _api_error(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"success": False, "error": msg}, status_code=status)


@app.post("/api/v1/prospect")
async def api_prospect(request: Request):
    """
    Draft a personalized outreach email for a single company.

    Body (JSON):
      company    — company name or URL (required)
      industry   — industry hint (optional)
      role       — candidate role to offer (optional, auto-detected)

    Returns the draft subject, body, contact info, and signals used.
    """
    user = _api_auth(request)
    if not user:
        return _api_error("Invalid or missing API key. Pass as: Authorization: Bearer outly_sk_...", 401)

    try:
        body = await request.json()
    except Exception:
        return _api_error("Request body must be valid JSON.")

    company = (body.get("company") or "").strip()
    if not company:
        return _api_error("'company' field is required.")

    industry = (body.get("industry") or "").strip() or None
    role = (body.get("role") or "").strip() or None

    try:
        output = run_pipeline(
            query=company,
            run_drafter=True,
            industry=industry,
            job_title=role,
            user_id=user["user_id"],
        )
        for result, chunks, draft_data in output:
            if draft_data:
                return JSONResponse({
                    "success": True,
                    "company_name": draft_data.get("company_name", result.title),
                    "company_url": result.url,
                    "contact_title": draft_data.get("contact_title"),
                    "contact_name": draft_data.get("contact_name"),
                    "contact_email": draft_data.get("contact_email"),
                    "role_to_offer": draft_data.get("role_to_offer"),
                    "subject": draft_data.get("subject"),
                    "body": draft_data.get("body"),
                    "rationale": draft_data.get("rationale"),
                    "hiring_signals": draft_data.get("hiring_signals", []),
                    "news_signals": [n.get("title") for n in draft_data.get("news_signals", [])],
                    "from_cache": draft_data.get("from_cache", False),
                })
        return _api_error("No draft generated. Company may lack sufficient web content.", 422)
    except Exception as e:
        log.exception("API prospect error")
        return _api_error(str(e), 500)


@app.post("/api/v1/resume")
async def api_resume(request: Request):
    """
    Find matching companies for a candidate and draft outreach emails.

    Body (JSON):
      resume_text   — candidate resume or skills summary (required)
      industry      — industry focus (optional)
      max_companies — number of companies to target, 1-10 (default 5)

    Returns a list of draft emails, one per company.
    """
    user = _api_auth(request)
    if not user:
        return _api_error("Invalid or missing API key. Pass as: Authorization: Bearer outly_sk_...", 401)

    try:
        body = await request.json()
    except Exception:
        return _api_error("Request body must be valid JSON.")

    resume_text = (body.get("resume_text") or "").strip()
    if not resume_text:
        return _api_error("'resume_text' field is required.")

    industry = (body.get("industry") or "").strip() or None
    max_companies = min(max(int(body.get("max_companies", 5)), 1), 10)

    try:
        results = run_resume_pipeline(
            resume_text=resume_text,
            max_companies=max_companies,
            industry=industry,
            user_id=user["user_id"],
        )
        return JSONResponse({
            "success": True,
            "count": len(results),
            "drafts": [
                {
                    "company_name": d.get("company_name"),
                    "company_url": d.get("company_url"),
                    "contact_title": d.get("contact_title"),
                    "contact_name": d.get("contact_name"),
                    "contact_email": d.get("contact_email"),
                    "role_to_offer": d.get("role_to_offer") or d.get("candidate_role"),
                    "subject": d.get("subject"),
                    "body": d.get("body"),
                    "rationale": d.get("rationale"),
                    "from_cache": d.get("from_cache", False),
                }
                for d in results
            ],
        })
    except Exception as e:
        log.exception("API resume error")
        return _api_error(str(e), 500)


@app.get("/api/v1/drafts")
async def api_list_drafts(request: Request, status: str = "", limit: int = 20):
    """List your saved drafts. Optional ?status=draft|approved|sent|rejected"""
    user = _api_auth(request)
    if not user:
        return _api_error("Invalid or missing API key.", 401)

    filter_status = status if status in ("draft", "approved", "sent", "rejected") else None
    drafts = list_drafts(status=filter_status, user_id=user["user_id"])
    return JSONResponse({
        "success": True,
        "count": len(drafts[:limit]),
        "drafts": [
            {
                "id": d.id,
                "company_name": d.company_name,
                "company_url": d.company_url,
                "subject": d.subject,
                "body": d.body,
                "status": d.status,
                "created_at": d.created_at,
            }
            for d in drafts[:limit]
        ],
    })


@app.get("/api/v1/drafts/{draft_id}")
async def api_get_draft(request: Request, draft_id: int):
    """Get a single draft by ID."""
    user = _api_auth(request)
    if not user:
        return _api_error("Invalid or missing API key.", 401)

    draft = get_draft(draft_id)
    if not draft or draft.user_id != user["user_id"]:
        return _api_error("Draft not found.", 404)

    return JSONResponse({
        "success": True,
        "draft": {
            "id": draft.id,
            "company_name": draft.company_name,
            "company_url": draft.company_url,
            "subject": draft.subject,
            "body": draft.body,
            "rationale": draft.rationale,
            "status": draft.status,
            "created_at": draft.created_at,
        },
    })


@app.get("/api/docs", response_class=HTMLResponse)
async def api_docs(request: Request):
    if (r := _require_auth(request)):
        return r
    return templates.TemplateResponse(request=request, name="api_docs.html", context={})


# ---------------------------------------------------------------------------
# Telegram Webhook
# ---------------------------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive updates from Telegram Bot API."""
    try:
        update = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    # Stray callback (e.g. an old button in chat history) — just acknowledge it.
    if "callback_query" in update:
        from tools.telegram_bot import answer_callback
        answer_callback(update["callback_query"]["id"],
                        "Applications are manual now — open the PDF and tap Apply.")
        return JSONResponse({"ok": True})

    # Message (text or document)
    if "message" in update:
        msg     = update["message"]
        chat_id = msg["chat"]["id"]

        if "document" in msg:
            threading.Thread(target=_tg_handle_resume, args=(msg, chat_id), daemon=True).start()
            return JSONResponse({"ok": True})

        text = (msg.get("text") or "").strip()
        if not text:
            return JSONResponse({"ok": True})

        if text.startswith("/applied_"):
            try:
                job_id = int(text.split("_", 1)[1])
                update_job_status(job_id, "applied")
                from tools.telegram_bot import send_message
                send_message(f"✅ Job #{job_id} marked as applied!")
            except Exception:
                pass
        elif text in ("/start", "/Start"):
            _tg_help(chat_id)
        elif text == "/status":
            _tg_status(chat_id)
        elif text == "/queue":
            threading.Thread(target=_tg_send_queue_pdf, args=(chat_id,), daemon=True).start()
        elif text == "/help":
            _tg_help(chat_id)
        else:
            from tools.telegram_bot import send_message
            send_message("I didn't recognize that. Send /help for commands, "
                         "/queue for your jobs PDF, or attach a resume PDF to update your profile.")

    return JSONResponse({"ok": True})


# ── Telegram action handlers ────────────────────────────────────────────────

def _tg_handle_resume(msg: dict, chat_id: int) -> None:
    from tools.telegram_bot import send_message
    from tools.resume_parser import parse_resume
    from llm.skills_extractor import extract_skills
    from storage.profiles import save_profile

    doc = msg.get("document", {})
    file_id = doc.get("file_id")
    file_name = doc.get("file_name", "")
    mime = doc.get("mime_type", "")

    is_pdf = "pdf" in mime or file_name.lower().endswith(".pdf")
    is_doc = any(file_name.lower().endswith(ext) for ext in (".doc", ".docx", ".txt"))

    if not (is_pdf or is_doc):
        send_message("Please send your resume as a PDF, DOCX, or TXT file.")
        return

    send_message("📄 Got your resume — parsing now…")

    from tools.telegram_bot import download_document
    raw = download_document(file_id)
    if not raw:
        send_message("⚠️ Could not download the file. Please try again.")
        return

    try:
        text = parse_resume(raw, file_name or "resume.pdf")
    except Exception as e:
        send_message(f"⚠️ Could not parse file: {e}")
        return

    if not text or len(text.strip()) < 50:
        send_message("⚠️ The file appears empty or unreadable. Try a PDF with selectable text.")
        return

    send_message("🔍 Extracting your skills and role…")
    try:
        profile = extract_skills(text)
    except Exception as e:
        send_message(f"⚠️ Skills extraction failed: {e}")
        return

    if not profile:
        send_message("⚠️ Could not extract profile. Try pasting your resume text via the web app.")
        return

    save_profile(profile)

    role   = profile.get("role_title", "Unknown")
    skills = ", ".join(profile.get("skills", [])[:6])
    send_message(
        f"✅ *Resume saved!*\n\n"
        f"*Role:* {role}\n"
        f"*Skills:* {skills}\n\n"
        f"I'll use this profile at the next scheduled job search (9:30 AM or 2:30 PM IST)."
    )


def _tg_send_queue_pdf(chat_id: int) -> None:
    """Build and send a PDF of all current queue/pending jobs on demand."""
    from tools.telegram_bot import send_message, send_document
    from tools.job_pdf import build_jobs_pdf
    from storage.jobs import list_job_applications

    user_id = get_scheduler_user_id()
    all_jobs = list_job_applications(user_id=user_id)
    # Show jobs not yet applied to: freshly queued + already sent in a digest
    active = [j for j in all_jobs if j.status in ("queued", "sent")]
    if not active:
        send_message("📭 No active jobs right now. Send your resume PDF or wait "
                     "for the next scheduled search (9:30 AM / 2:30 PM IST).")
        return
    try:
        pdf_bytes = build_jobs_pdf(active, title="Job Review Queue")
        send_document(pdf_bytes, filename="outly_jobs.pdf",
                      caption=f"Your {len(active)} active jobs with full details.")
    except Exception as e:
        log.error("Failed to send queue PDF: %s", e)
        send_message(f"⚠️ Could not build the PDF: {e}")


def _tg_status(chat_id: int) -> None:
    from tools.telegram_bot import send_message
    from storage.jobs import list_job_applications
    user_id = get_scheduler_user_id()
    all_jobs = list_job_applications(user_id=user_id)
    counts = {}
    for j in all_jobs:
        counts[j.status] = counts.get(j.status, 0) + 1

    lines = [f"📊 *Job Application Status*\n"]
    for status, count in sorted(counts.items()):
        emoji = {"queued": "⏳", "telegram_pending": "👀", "awaiting_feedback": "📝",
                 "approved": "✅", "applied": "🎉", "rejected": "❌"}.get(status, "•")
        lines.append(f"{emoji} {status.replace('_', ' ').title()}: {count}")
    send_message("\n".join(lines))


@app.get("/telegram/test")
async def telegram_test(request: Request):
    """Dev helper — verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID by sending a test message."""
    from config import get_telegram_token, get_telegram_chat_id
    import requests as _req

    token   = get_telegram_token()
    chat_id = get_telegram_chat_id()

    if not token:
        return JSONResponse({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set in .env"}, status_code=500)
    if not chat_id:
        return JSONResponse({"ok": False, "error": "TELEGRAM_CHAT_ID not set in .env"}, status_code=500)

    # Call Telegram API directly so we can return the raw error
    try:
        resp = _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       "👋 *Outly bot connected!* Token and Chat ID are working.",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Network error: {e}"}, status_code=500)

    if data.get("ok"):
        return JSONResponse({"ok": True, "message_id": data["result"]["message_id"], "chat_id": chat_id})

    # Return the raw Telegram error so we know exactly what's wrong
    return JSONResponse({
        "ok":          False,
        "tg_error":    data.get("description"),
        "error_code":  data.get("error_code"),
        "token_used":  f"{token[:10]}...{token[-4:]}",
        "chat_id_used": chat_id,
    }, status_code=500)


@app.get("/telegram/webhook-info")
async def telegram_webhook_info():
    """Show current webhook status from Telegram."""
    from config import get_telegram_token
    import requests as _req
    token = get_telegram_token()
    if not token:
        return JSONResponse({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}, status_code=500)
    resp = _req.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
    return JSONResponse(resp.json())


@app.post("/telegram/set-webhook")
async def telegram_set_webhook(request: Request, url: str = None):
    """
    Manually register a webhook URL. Useful for local dev with ngrok.
    POST /telegram/set-webhook?url=https://xxxx.ngrok.io
    """
    from tools.telegram_bot import register_webhook
    if not url:
        body = await request.json()
        url = body.get("url", "")
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    webhook_url = f"{url.rstrip('/')}/telegram/webhook"
    ok = register_webhook(webhook_url)
    return JSONResponse({"ok": ok, "webhook_url": webhook_url})


# ---------------------------------------------------------------------------
# External cron trigger — reliable scheduling that survives free-tier sleep
# ---------------------------------------------------------------------------

@app.api_route("/tasks/run-search", methods=["GET", "POST"])
async def tasks_run_search(request: Request, token: str = ""):
    """
    Run the scheduled job search on demand. Intended for an external cron
    (cron-job.org, UptimeRobot, GitHub Actions) so the search fires reliably
    even when Render's free tier has spun the in-process scheduler to sleep —
    the incoming request itself wakes the service.

    Auth: pass ?token=<CRON_SECRET>  (or X-Cron-Secret header).
    Runs in a background thread and returns immediately.
    """
    from config import get_cron_secret

    secret = get_cron_secret()
    if not secret:
        return JSONResponse(
            {"ok": False, "error": "CRON_SECRET not set on the server. Set it in Render env vars."},
            status_code=503,
        )

    provided = token or request.headers.get("X-Cron-Secret", "")
    if provided != secret:
        return JSONResponse({"ok": False, "error": "Invalid or missing token."}, status_code=401)

    def _run():
        try:
            from scheduler.job_runner import run_scheduled_search
            run_scheduled_search()
        except Exception:
            log.exception("tasks/run-search failed")

    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"ok": True, "status": "search started — watch Telegram for the PDF"})


def _tg_help(chat_id: int) -> None:
    from tools.telegram_bot import send_message
    send_message(
        "🤖 *Outly Job Bot*\n\n"
        "I search jobs for you on a schedule and send a *PDF* of the best matches. "
        "Each job has a tappable *Apply* link — open the PDF, pick the ones you like, "
        "and apply directly.\n\n"
        "*Commands*\n"
        "📄 *Send a resume PDF* — update your profile (used in the next search)\n"
        "/queue — Get the PDF of your current matched jobs\n"
        "/status — Show job counts by status\n"
        "`/applied_ID` — Mark job #ID as applied\n"
        "/help — Show this message\n\n"
        "🕐 *Auto-schedule:* Weekdays 9:30 AM & 2:30 PM IST\n"
        "Mon: 20 jobs | Other days: 10 jobs"
    )


# ---------------------------------------------------------------------------
# Job Application Automation
# ---------------------------------------------------------------------------

_JOB_STEP_LABELS = {
    "parsing_resume": "📄 Parsing resume...",
    "extracting":     "🔍 Extracting candidate profile...",
    "profile_ready":  "✅ Profile extracted",
    "searching":      "🔎 Searching LinkedIn & Indeed...",
    "scoring":        "🧠 Scoring job matches...",
    "generating":     "✍️  Writing cover letters...",
    "saving":         "💾 Saving to review queue...",
    "done":           "🎉 Jobs queued for your review!",
    "error":          "❌ Error",
}


def _run_job_search_thread(
    job_id: str,
    resume_text: str,
    keywords: str,
    location: str,
    min_score: int,
    remote_only: bool,
    user_id: int | None,
    candidate_name: str,
) -> None:
    from llm.skills_extractor import extract_skills
    from tools.job_search import search_jobs
    from llm.job_matcher import score_jobs_parallel
    from llm.cover_letter import generate_cover_letter

    def emit(step: str, detail: str = "") -> None:
        label = _JOB_STEP_LABELS.get(step, step)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["events"].append({"step": step, "label": label, "detail": detail})

    try:
        init_db()
        init_jobs_table()

        emit("extracting", "Reading your resume...")
        profile = extract_skills(resume_text)
        if not profile:
            emit("error", "Could not extract profile from resume. Try pasting the text directly.")
            with _jobs_lock:
                _jobs[job_id]["done"] = True
            return

        role_title = profile.get("role_title", "Software Engineer")
        skills = profile.get("skills", [])
        summary = profile.get("summary", "")
        emit("profile_ready", f"Role: {role_title} | Skills: {', '.join(skills[:5])}")

        # Resolve seniority (env override or derived from resume years)
        from config import get_candidate_level, is_seniority_strict
        from tools.seniority import level_from_years, filter_by_level, search_query_for_level
        level = get_candidate_level() or level_from_years(profile.get("experience_years"))
        strict = is_seniority_strict()
        profile["level"] = level

        # Search jobs (bias query to level unless the user typed their own keywords)
        base_query = keywords.strip() if keywords.strip() else role_title
        query = base_query if keywords.strip() else search_query_for_level(base_query, level)
        emit("searching", f"Searching for '{query}' in {location}...")
        listings = search_jobs(
            query=query,
            location=location or "Remote",
            results_per_site=20,
            hours_old=168,
            remote_only=remote_only,
        )

        if not listings:
            emit("error", "No jobs found. Try different keywords or location.")
            with _jobs_lock:
                _jobs[job_id]["done"] = True
                _jobs[job_id]["result"] = {"saved": 0}
            return

        # Drop over-level roles, then filter already-saved (one batched query)
        listings, dropped = filter_by_level(listings, level, strict)
        if dropped:
            emit("scoring", f"Filtered {dropped} roles above your {level} level...")
        existing_urls = get_existing_job_urls(user_id)
        new_listings = [l for l in listings if l.job_url not in existing_urls]
        emit("scoring", f"Scoring {len(new_listings)} {level}-level jobs...")

        if not new_listings:
            emit("done", "All found jobs are already in your queue.")
            with _jobs_lock:
                _jobs[job_id]["done"] = True
                _jobs[job_id]["result"] = {"saved": 0}
            return

        # Score in parallel
        job_dicts = [
            {
                "title":       l.title,
                "company":     l.company,
                "location":    l.location,
                "description": l.description,
                "job_url":     l.job_url,
                "is_remote":   l.is_remote,
                "date_posted": l.date_posted,
                "source":      l.source,
                "apply_method":l.apply_method,
                "contact_email": l.contact_email,
                "ats_url":     l.ats_url,
                "company_url": l.company_url,
            }
            for l in new_listings
        ]
        candidate_profile_for_scoring = {
            "role_title": role_title,
            "skills": skills,
            "summary": summary,
            "industries": profile.get("industries", []),
            "level": level,
            "experience_years": profile.get("experience_years", "0-1"),
        }
        scored = score_jobs_parallel(job_dicts, candidate_profile_for_scoring)
        above_threshold = [j for j in scored if j.get("score", 0) >= min_score]

        # Cap auto-generated cover letters to the top matches; the rest save
        # without one and get a letter on demand via the "Generate" button.
        MAX_LETTERS = 10
        letter_targets = {id(j) for j in above_threshold[:MAX_LETTERS]}
        emit("generating",
             f"Writing cover letters for top {len(letter_targets)} of "
             f"{len(above_threshold)} matches (score ≥ {min_score})...")

        saved_count = 0
        for job in scored:
            score = job.get("score", 0)
            cover_letter = ""
            subject_line = f"Application for {job['title']} — {candidate_name or role_title}"

            if id(job) in letter_targets:
                try:
                    cl_result = generate_cover_letter(
                        job_title=job["title"],
                        company=job["company"],
                        location=job.get("location", ""),
                        description=job.get("description", ""),
                        candidate_profile=candidate_profile_for_scoring,
                        candidate_name=candidate_name,
                    )
                    cover_letter = cl_result.get("cover_letter", "")
                    subject_line = cl_result.get("subject_line", subject_line)
                except Exception as e:
                    log.warning("Cover letter failed for %s: %s", job["title"], e)

            try:
                save_job_application(
                    user_id=user_id,
                    job_title=job["title"],
                    company_name=job["company"],
                    job_url=job["job_url"],
                    location=job.get("location", ""),
                    is_remote=bool(job.get("is_remote", False)),
                    date_posted=job.get("date_posted", ""),
                    source=job.get("source", ""),
                    job_description=job.get("description", ""),
                    match_score=score,
                    match_rationale=job.get("rationale", ""),
                    key_matches=job.get("key_matches", []),
                    gaps=job.get("gaps", []),
                    cover_letter=cover_letter,
                    subject_line=subject_line,
                    apply_method=job.get("apply_method", "manual"),
                    contact_email=job.get("contact_email"),
                    ats_url=job.get("ats_url"),
                    company_url=job.get("company_url"),
                    candidate_name=candidate_name,
                    candidate_role=role_title,
                )
                saved_count += 1
            except Exception as e:
                log.warning("Could not save job %s: %s", job["title"], e)

        emit("done", f"Saved {saved_count} jobs to your review queue.")
        with _jobs_lock:
            _jobs[job_id]["done"] = True
            _jobs[job_id]["result"] = {"saved": saved_count}

    except Exception as e:
        log.exception("Job search error for job_id=%s", job_id)
        with _jobs_lock:
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["done"] = True
        emit("error", str(e))


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, job_id: str = None):
    if (r := _require_auth(request)):
        return r
    return templates.TemplateResponse(
        request=request, name="jobs.html",
        context={"job_id": job_id, "error": None},
    )


@app.post("/jobs", response_class=HTMLResponse)
async def jobs_search(
    request: Request,
    resume_file: UploadFile = File(None),
    resume_text: str = Form(""),
    keywords: str = Form(""),
    location: str = Form("Remote"),
    min_score: int = Form(60),
    remote_only: bool = Form(False),
    candidate_name: str = Form(""),
):
    if (r := _require_auth(request)):
        return r

    from tools.resume_parser import parse_resume

    text = ""
    if resume_file and resume_file.filename:
        raw = await resume_file.read()
        text = parse_resume(raw, resume_file.filename)
    if not text and resume_text.strip():
        text = resume_text.strip()
    if not text:
        return templates.TemplateResponse(
            request=request, name="jobs.html",
            context={"job_id": None, "error": "Please upload a PDF resume or paste your resume text."},
        )

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"events": [], "done": False, "result": None, "error": None}

    threading.Thread(
        target=_run_job_search_thread,
        args=(
            job_id, text, keywords, location or "Remote",
            min(max(min_score, 0), 100), bool(remote_only),
            _current_user_id(request), candidate_name.strip(),
        ),
        daemon=True,
    ).start()

    return RedirectResponse(url=f"/jobs?job_id={job_id}", status_code=303)


@app.get("/jobs/queue", response_class=HTMLResponse)
async def jobs_queue(request: Request, status: str = ""):
    if (r := _require_auth(request)):
        return r
    init_jobs_table()
    filter_status = status if status in ("queued", "approved", "applied", "rejected") else None
    jobs = list_job_applications(
        user_id=_current_user_id(request),
        status=filter_status,
    )
    return templates.TemplateResponse(
        request=request, name="jobs_queue.html",
        context={"jobs": jobs, "filter_status": filter_status or "all"},
    )


@app.get("/jobs/{job_app_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_app_id: int):
    if (r := _require_auth(request)):
        return r
    job = get_job_application(job_app_id)
    if not job:
        return HTMLResponse(content="Job not found.", status_code=404)
    return templates.TemplateResponse(
        request=request, name="job_detail.html",
        context={"job": job},
    )


@app.post("/jobs/{job_app_id}/approve")
async def job_approve(request: Request, job_app_id: int):
    if (r := _require_auth(request)):
        return r
    job = get_job_application(job_app_id)
    if not job:
        return HTMLResponse("Job not found.", status_code=404)

    if job.apply_method == "email" and job.contact_email:
        from tools.email_sender import send_application_email
        success = send_application_email(
            to_email=job.contact_email,
            subject=job.subject_line or f"Application for {job.job_title}",
            body=job.cover_letter or "",
            from_name=job.candidate_name or "",
        )
        update_job_status(job_app_id, "applied" if success else "approved")
        return RedirectResponse(url=f"/jobs/{job_app_id}?applied={'1' if success else '0'}", status_code=303)
    else:
        # ATS / manual — mark approved, redirect to job URL in detail page
        update_job_status(job_app_id, "approved")
        return RedirectResponse(url=f"/jobs/{job_app_id}?ats=1", status_code=303)


@app.post("/jobs/{job_app_id}/reject")
async def job_reject(request: Request, job_app_id: int):
    if (r := _require_auth(request)):
        return r
    update_job_status(job_app_id, "rejected")
    return RedirectResponse(url="/jobs/queue", status_code=303)


@app.post("/jobs/{job_app_id}/applied")
async def job_mark_applied(request: Request, job_app_id: int):
    if (r := _require_auth(request)):
        return r
    update_job_status(job_app_id, "applied")
    return RedirectResponse(url="/jobs/queue", status_code=303)


@app.post("/jobs/{job_app_id}/generate-letter")
async def job_generate_letter(request: Request, job_app_id: int):
    if (r := _require_auth(request)):
        return r
    job = get_job_application(job_app_id)
    if not job:
        return HTMLResponse("Job not found.", status_code=404)

    from llm.cover_letter import generate_cover_letter
    from storage.profiles import load_profile
    profile = load_profile() or {}
    try:
        cl = generate_cover_letter(
            job_title=job.job_title,
            company=job.company_name,
            location=job.location,
            description=job.job_description,
            candidate_profile=profile,
            candidate_name=job.candidate_name or "",
        )
        update_cover_letter(job_app_id, cl.get("cover_letter", ""))
    except Exception as e:
        log.error("Cover letter generation failed: %s", e)
    return RedirectResponse(url=f"/jobs/{job_app_id}", status_code=303)


@app.post("/jobs/{job_app_id}/save-letter")
async def job_save_letter(
    request: Request,
    job_app_id: int,
    cover_letter: str = Form(...),
):
    if (r := _require_auth(request)):
        return r
    update_cover_letter(job_app_id, cover_letter)
    return RedirectResponse(url=f"/jobs/{job_app_id}", status_code=303)


# ---------------------------------------------------------------------------
# Dev server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER") else "127.0.0.1"
    print(f"Starting Web Server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, workers=1)
