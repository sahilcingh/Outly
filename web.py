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

from main import run_pipeline, run_batch_csv
from storage.drafts import (
    get_draft,
    init_db,
    list_drafts,
    save_draft,
    update_draft_status,
)

log = logging.getLogger(__name__)

app = FastAPI(title="B2B Prospecting Agent")

os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

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
        log.exception("Pipeline error for job %s", job_id)
        with _jobs_lock:
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["done"] = True
        _push(job_id, "error", str(e))


# ---------------------------------------------------------------------------
# Home — single prospect form
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"result": None, "error": None, "job_id": None},
    )


@app.post("/", response_class=HTMLResponse)
async def run_agent(
    request: Request,
    query: str = Form(...),
    industry: str = Form(None),
    job_title: str = Form(None),
):
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"events": [], "done": False, "result": None, "url": None, "error": None}

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(job_id, query, industry or None, job_title or None),
        daemon=True,
    )
    thread.start()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"result": None, "error": None, "job_id": job_id, "query": query},
    )


# ---------------------------------------------------------------------------
# SSE — stream pipeline progress events to the browser
# ---------------------------------------------------------------------------

@app.get("/stream/{job_id}")
async def stream_events(job_id: str):
    async def generator():
        last_sent = 0
        max_wait = 180  # seconds before timeout
        waited = 0

        while waited < max_wait:
            with _jobs_lock:
                job = _jobs.get(job_id)

            if not job:
                yield f"data: {json.dumps({'step': 'error', 'label': '❌ Job not found', 'detail': ''})}\n\n"
                return

            events = job["events"]
            # Send any new events
            while last_sent < len(events):
                yield f"data: {json.dumps(events[last_sent])}\n\n"
                last_sent += 1

            if job["done"]:
                # Send final result payload
                payload = {"step": "__result__", "result": job["result"], "url": job["url"]}
                yield f"data: {json.dumps(payload)}\n\n"
                return

            await asyncio.sleep(0.3)
            waited += 0.3

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
    try:
        from llm.drafter import PROMPT_VERSION
        save_draft(
            company_name=company_name[:200],
            company_url=company_url,
            subject=subject,
            body=body,
            rationale=rationale or "Manually edited draft",
            prompt_version=PROMPT_VERSION,
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
# Batch upload — CSV file
# ---------------------------------------------------------------------------

@app.get("/batch", response_class=HTMLResponse)
async def batch_form(request: Request):
    return templates.TemplateResponse(request=request, name="batch.html", context={"message": None, "error": None})


@app.post("/batch", response_class=HTMLResponse)
async def batch_upload(request: Request, file: UploadFile = File(...)):
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
    init_db()
    filter_status = status if status in ("draft", "approved", "sent", "rejected") else None
    drafts = list_drafts(status=filter_status)
    return templates.TemplateResponse(
        request=request,
        name="drafts.html",
        context={"drafts": drafts, "filter_status": filter_status or "all"},
    )


@app.get("/drafts/{draft_id}", response_class=HTMLResponse)
async def draft_detail(request: Request, draft_id: int):
    init_db()
    draft = get_draft(draft_id)
    if not draft:
        return HTMLResponse(content="Draft not found.", status_code=404)
    return templates.TemplateResponse(request=request, name="draft_detail.html", context={"draft": draft})


@app.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int):
    update_draft_status(draft_id, "approved")
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/{draft_id}/reject")
async def reject_draft(draft_id: int):
    update_draft_status(draft_id, "rejected")
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/{draft_id}/sent")
async def mark_sent(draft_id: int):
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
