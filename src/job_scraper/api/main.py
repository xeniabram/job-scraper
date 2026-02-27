import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from job_scraper.config import settings
from job_scraper.scraper import AVAILABLE_SOURCES
from job_scraper.storage import ResultsStorage

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/review")
async def review():
    return FileResponse(STATIC_DIR / "review.html")

@app.get("/rejected-review")
async def rejected_review():
    return FileResponse(STATIC_DIR / "rejected_review.html")

@app.get("/stats")
async def stats():
    return FileResponse(STATIC_DIR / "stats.html")


# ── WebSockets ───────────────────────────────────────────────────────────────

async def _run_command(websocket: WebSocket, commands: list[str]) -> None:
    await websocket.accept()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "job_scraper.main", *commands,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if process.stdout:
        async for line in process.stdout:
            await websocket.send_text(line.decode())
    await websocket.close()


@app.websocket("/scrape")
async def scrape(websocket: WebSocket, source: list[str] = Query(default=[])):
    valid = {s for s in source if s in AVAILABLE_SOURCES}
    commands = ["scrape"] + (["--sources"] + list(valid) if valid else [])
    await _run_command(websocket, commands)

@app.websocket("/filter")
async def filter_jobs(websocket: WebSocket):
    await _run_command(websocket, ["filter"])

@app.websocket("/optimize")
async def optimize(websocket: WebSocket):
    await _run_command(websocket, ["optimize"])


# ── Misc ─────────────────────────────────────────────────────────────────────

@app.post("/jobs")
async def receive_jobs(request: Request):
    body = await request.body()
    filename = settings.saved_jobs_dir / f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename.write_bytes(body)
    return {"status": "ok", "file": filename.name}

@app.get("/api/sources")
async def get_sources():
    return list(AVAILABLE_SOURCES)

@app.get("/api/stats")
async def get_daily_stats():
    return ResultsStorage(settings.data_dir).get_daily_stats()


# ── Review (matched jobs) ─────────────────────────────────────────────────────

@app.get("/api/review/jobs")
async def get_review_jobs():
    return ResultsStorage(settings.data_dir).load_unapplied_matched()

@app.get("/api/review/count")
async def get_review_count():
    return {"count": ResultsStorage(settings.data_dir).load_unapplied_matched_count()}

@app.post("/api/review/applied")
async def mark_applied(request: Request):
    body = await request.json()
    ResultsStorage(settings.data_dir).mark_applied(body["url"])
    return {"status": "ok"}

@app.post("/api/review/reject")
async def reject_job(request: Request):
    body = await request.json()
    ResultsStorage(settings.data_dir).reject_manually(body["url"], body["reason"])
    return {"status": "ok"}


# ── Rejected review ───────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    url: str
    reason: str

class IncorrectRequest(BaseModel):
    url: str
    llm_reason: str
    user_note: str


def _find_rejected_job(storage: ResultsStorage, url: str) -> dict[str, Any]:
    for job in storage.load_unreviewed_rejected():
        if job.get("url") == url:
            return job
    raise HTTPException(status_code=404, detail=f"Job not found: {url}")


@app.get("/api/rejected/jobs")
async def get_rejected_jobs():
    return ResultsStorage(settings.data_dir).load_unreviewed_rejected()

@app.get("/api/rejected/count")
async def get_rejected_count():
    return {"count": len(ResultsStorage(settings.data_dir).load_unreviewed_rejected())}

@app.get("/api/rejected/scraped")
async def get_scraped_details(url: str):
    details = ResultsStorage(settings.data_dir).get_scraped_details(url)
    if details is None:
        raise HTTPException(status_code=404, detail="No scraped details found.")
    return details

@app.post("/api/rejected/approve")
async def approve_rejection(body: ApproveRequest):
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="Reason must not be empty.")
    storage = ResultsStorage(settings.data_dir)
    job = _find_rejected_job(storage, body.url)
    scraped: dict[str, Any] = storage.get_scraped_details(body.url) or {}
    storage.save_to_learn(
        url=body.url,
        title=job.get("role") or "",
        company=scraped.get("company") or "",
        reason=body.reason.strip(),
        correct_label="rejected",
        skillset_match_percent=job.get("skillset_match_percent", 0),
    )
    return {"status": "ok"}

@app.post("/api/rejected/incorrect")
async def mark_rejected_incorrectly(body: IncorrectRequest):
    if not body.user_note.strip():
        raise HTTPException(status_code=422, detail="User note must not be empty.")
    storage = ResultsStorage(settings.data_dir)
    job = _find_rejected_job(storage, body.url)
    scraped: dict[str, Any] = storage.get_scraped_details(body.url) or {}
    storage.promote_to_matched(
        url=body.url,
        title=job.get("role") or "",
        company=scraped.get("company") or "",
        llm_reason=body.llm_reason,
        user_note=body.user_note.strip(),
        skillset_match_percent=job.get("skillset_match_percent", 0),
    )
    return {"status": "ok"}


# ── Entry point ───────────────────────────────────────────────────────────────

def serve():
    uvicorn.run("job_scraper.api.main:app", host="0.0.0.0", port=8000, reload=True)