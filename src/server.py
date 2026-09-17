import asyncio
import json
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from .video_pipeline import run as _run_pipeline

SOURCE     = "input/4156510-hd_1920_1080_30fps.mp4"
CLEAN_OUT  = "output/clean.mp4"
ANIM_OUT   = "output/animated.mp4"

# shared between pipeline thread and websocket handlers
_snapshot: dict = {}
_lock = threading.Lock()
_clients: list[WebSocket] = []
_clients_lock = asyncio.Lock()


def _on_snapshot(snap: dict) -> None:
    with _lock:
        _snapshot.clear()
        _snapshot.update(snap)


def _pipeline_worker() -> None:
    _run_pipeline(
        source=SOURCE,
        clean_path=CLEAN_OUT,
        anim_path=ANIM_OUT,
        on_snapshot=_on_snapshot,
        headless=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_pipeline_worker, daemon=True)
    t.start()
    print(f"Pipeline started — processing {SOURCE}")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    with _lock:
        snap = dict(_snapshot)
    return {"status": "ok", "has_data": bool(snap)}


@app.websocket("/ws/metrics")
async def ws_metrics(ws: WebSocket):
    await ws.accept()
    print(f"Client connected: {ws.client}")
    try:
        while True:
            with _lock:
                snap = dict(_snapshot)
            if snap:
                await ws.send_text(json.dumps(snap))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        print(f"Client disconnected: {ws.client}")


def start(host: str = "0.0.0.0", port: int = 8000) -> None:
    uvicorn.run(app, host=host, port=port)
