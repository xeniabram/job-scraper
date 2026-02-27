import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from job_scraper.config import settings
from job_scraper.exceptions import JobNotFound
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
async def scrape(websocket: WebSocket, source: Annotated[list[str] | None, Query()] = None):
    valid = {s for s in source if source in AVAILABLE_SOURCES} if source is not None else set()
    commands = ["scrape"] + (["--sources", *valid] if valid else [])
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
    return ResultsStorage(settings.data_dir).load_optimized_matched()

@app.get("/api/review/count")
async def get_review_count():
    return {"count": ResultsStorage(settings.data_dir).count_optimized_matched()}

@app.post("/api/review/applied")
async def mark_applied(request: Request):
    body = await request.json()
    try:
        ResultsStorage(settings.data_dir).mark_applied(body["url"])
    except JobNotFound as e:
        raise HTTPException(status_code=404, detail="Job not found.") from e
    return {"status": "ok"}

@app.post("/api/review/reject")
async def reject_job(request: Request):
    body = await request.json()
    try:
        ResultsStorage(settings.data_dir).reject_manually(body["url"], body["reason"])
    except JobNotFound as e:
        raise HTTPException(status_code=404, detail="Job not found.") from e
    return {"status": "ok"}


# ── Rejected review ───────────────────────────────────────────────────────────

class ConfirmRejectionRequest(BaseModel):
    url: str

class PromoteRequest(BaseModel):
    url: str
    user_note: str


@app.get("/api/rejected/jobs")
async def get_rejected_jobs():
    return ResultsStorage(settings.data_dir).load_unreviewed_rejected()

@app.get("/api/rejected/count")
async def get_rejected_count():
    return {"count": len(ResultsStorage(settings.data_dir).load_unreviewed_rejected())}

@app.post("/api/rejected/confirm")
async def confirm_rejection(body: ConfirmRejectionRequest):
    try:
        ResultsStorage(settings.data_dir).confirm_rejection(body.url)
    except JobNotFound as e:
        raise HTTPException(status_code=404, detail="Job not found.") from e
    return {"status": "ok"}

@app.post("/api/rejected/promote")
async def promote_to_matched(body: PromoteRequest):
    if not body.user_note.strip():
        raise HTTPException(status_code=422, detail="User note must not be empty.")
    try:
        ResultsStorage(settings.data_dir).promote_to_matched(body.url, user_note=body.user_note.strip())
    except JobNotFound as e:
        raise HTTPException(status_code=404, detail="Job not found.") from e
    return {"status": "ok"}


# ── Entry point ───────────────────────────────────────────────────────────────

def serve():
    uvicorn.run("job_scraper.api.main:app", host="0.0.0.0", port=8000)


def serve_dev():
    uvicorn.run("job_scraper.api.main:app", host="0.0.0.0", port=8000, reload=True)
