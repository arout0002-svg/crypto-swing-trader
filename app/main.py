"""
FastAPI application entry point.

Startup:
  - Initialise database tables
  - Start APScheduler for 10-min trading scans
  - Register API routers
  - Serve the trading dashboard UI
  - Expose WebSocket /ws for live updates
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import backtest, dashboard, signals, trades
from app.core.config import get_settings
from app.core.database import init_db
from app.scheduler import job_runner

logging.basicConfig(
    level=logging.DEBUG if get_settings().DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        logger.info("WS client connected — total: %d", len(self._clients))

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws) if hasattr(self._clients, "discard") else None
        if ws in self._clients:
            self._clients.remove(ws)
        logger.info("WS client disconnected — total: %d", len(self._clients))

    async def broadcast(self, payload: dict):
        if not self._clients:
            return
        msg = json.dumps(payload)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def _broadcast_event(event: dict):
    await manager.broadcast(event)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s on port %d", settings.APP_NAME, settings.PORT)
    init_db()
    job_runner.set_broadcast(_broadcast_event)
    job_runner.start_scheduler()
    yield
    job_runner.stop_scheduler()
    logger.info("Shutdown complete")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AI-assisted crypto swing trading system",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(signals.router,   prefix="/api/v1")
app.include_router(trades.router,    prefix="/api/v1")
app.include_router(backtest.router,  prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; client can send ping
            data = await asyncio.wait_for(ws.receive_text(), timeout=30)
            if data == "ping":
                await ws.send_text('{"type":"pong"}')
    except (WebSocketDisconnect, asyncio.TimeoutError):
        manager.disconnect(ws)
    except Exception as exc:
        logger.debug("WS error: %s", exc)
        manager.disconnect(ws)


# ── UI route ──────────────────────────────────────────────────────────────────

UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    if UI_PATH.exists():
        return FileResponse(str(UI_PATH))
    return HTMLResponse("<h1>UI not found — check ui/index.html</h1>", status_code=404)


@app.get("/health")
def health():
    from app.core.database import health_check
    return {
        "status": "ok",
        "db": "ok" if health_check() else "error",
        "scheduler": "running" if (
            job_runner._scheduler and job_runner._scheduler.running
        ) else "stopped",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
