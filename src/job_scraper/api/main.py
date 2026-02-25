import asyncio
import sys

import uvicorn
from fastapi import FastAPI, WebSocket

app = FastAPI()
async def helper(websocket: WebSocket, commands: list[str]):
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
async def scrape(websocket: WebSocket):
    await helper(websocket=websocket, commands=["scrape"])

@app.websocket("/filter")
async def filter(websocket: WebSocket):
    await helper(websocket=websocket, commands=["filter"])

@app.websocket("/optimize")
async def optimize(websocket: WebSocket):
    await helper(websocket=websocket, commands=["optimize"])

    

def serve():
    uvicorn.run("job_scraper.api.main:app", host="0.0.0.0", port=8000, reload=True)