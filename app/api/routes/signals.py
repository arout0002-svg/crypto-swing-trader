"""API routes for signals and manual trigger."""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.routes import logs as api_logs
from app.core.database import get_db
from app.models.db_models import Signal
from app.scheduler.job_runner import trigger_now

router = APIRouter(prefix="/signals", tags=["signals"])
logger = logging.getLogger(__name__)


class SignalOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    signal_type: str
    close_price: Optional[float]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    position_size_inr: Optional[float]
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    volume_ratio: Optional[float]
    ai_confidence: Optional[int]
    ai_reasoning: Optional[str]
    ai_decision: Optional[str]
    alert_sent: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[SignalOut])
def list_signals(
    symbol: Optional[str] = Query(None),
    signal_type: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
):
    """List recent signals, optionally filtered by symbol or type."""
    with get_db() as db:
        q = db.query(Signal).order_by(Signal.created_at.desc())
        if symbol:
            q = q.filter(Signal.symbol == symbol)
        if signal_type:
            q = q.filter(Signal.signal_type == signal_type.upper())
        return q.limit(limit).all()


@router.get("/stats")
def signal_stats():
    """Aggregate signal statistics for the dashboard."""
    with get_db() as db:
        total  = db.query(Signal).count()
        buys   = db.query(Signal).filter(Signal.signal_type == "BUY").count()
        sells  = db.query(Signal).filter(Signal.signal_type == "SELL").count()
        alerted = db.query(Signal).filter(Signal.alert_sent == True).count()
        avg_conf = db.query(Signal).filter(Signal.ai_confidence.isnot(None)).with_entities(
            Signal.ai_confidence
        ).all()
        avg_c = round(sum(r[0] for r in avg_conf) / len(avg_conf), 1) if avg_conf else 0
    return {
        "total": total,
        "buys": buys,
        "sells": sells,
        "holds": total - buys - sells,
        "alerts_sent": alerted,
        "avg_confidence": avg_c,
    }


@router.post("/scan")
def manual_scan():
    """Manually trigger one scan pipeline run (for testing)."""
    import time
    logger.info("Manual scan triggered via API")
    t0 = time.time()
    result = trigger_now()
    dur = int((time.time() - t0) * 1000)
    api_logs.push(
        endpoint="/api/v1/signals/scan",
        method="POST",
        payload={"trigger": "manual"},
        response=result,
        status=result.get("status", "SUCCESS"),
        duration_ms=dur,
    )
    return {"status": "ok", "result": result}
