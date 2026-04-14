"""
API request/response log store — in-memory ring buffer (last 100 entries).
Each scan pipeline call appends a detailed log entry accessible via /api/v1/logs.
"""
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/logs", tags=["logs"])

_lock = Lock()
_logs: deque = deque(maxlen=100)
_counter = 0


def push(
    endpoint: str,
    method: str,
    payload: Any,
    response: Any,
    status: str = "success",
    duration_ms: int = 0,
):
    global _counter
    with _lock:
        _counter += 1
        _logs.appendleft(
            {
                "id": _counter,
                "ts": datetime.now(timezone.utc).isoformat(),
                "endpoint": endpoint,
                "method": method,
                "payload": payload,
                "response": response,
                "status": status,
                "duration_ms": duration_ms,
            }
        )


def all_logs() -> list:
    with _lock:
        return list(_logs)


@router.get("/")
def get_logs(limit: int = 50):
    """Return the last N API log entries with full request/response."""
    return all_logs()[:limit]
