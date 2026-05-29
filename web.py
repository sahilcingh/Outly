import asyncio
import csv
import io
import json
import logging
import os
import threading
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import get_secret_key
from main import run_pipeline, run_batch_csv, run_resume_pipeline
from tools.resume_parser import parse_resume
from storage.users import create_user, verify_login, init_users_table
from storage.drafts import (
    get_draft,
    init_db,
    list_drafts,
    save_draft,
    update_draft_status,
)

log = logging.getLogger(__name__)

app = FastAPI(title="B2B Prospecting Agent")
app.add_middleware(SessionMiddleware, secret_key=get_secret_key(), max_age=86400 * 7)  # 7-day sessions


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
# Dev server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER") else "127.0.0.1"
    print(f"Starting Web Server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, workers=1)
