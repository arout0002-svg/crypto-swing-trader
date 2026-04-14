"""API routes for backtesting."""
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import BacktestResult
from app.trading.backtester import run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    candles: int = 300


def _result_to_dict(r: BacktestResult) -> dict:
    """Safely serialise ORM BacktestResult to a plain dict."""
    def _dt(v):
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    return {
        "id":               r.id,
        "symbol":           r.symbol,
        "timeframe":        r.timeframe,
        "start_date":       _dt(r.start_date),
        "end_date":         _dt(r.end_date),
        "total_trades":     r.total_trades,
        "winning_trades":   r.winning_trades,
        "losing_trades":    r.losing_trades,
        "win_rate":         float(r.win_rate)          if r.win_rate          is not None else None,
        "total_return_pct": float(r.total_return_pct)  if r.total_return_pct  is not None else None,
        "max_drawdown_pct": float(r.max_drawdown_pct)  if r.max_drawdown_pct  is not None else None,
        "sharpe_ratio":     float(r.sharpe_ratio)      if r.sharpe_ratio      is not None else None,
        "avg_win_pct":      float(r.avg_win_pct)       if r.avg_win_pct       is not None else None,
        "avg_loss_pct":     float(r.avg_loss_pct)      if r.avg_loss_pct      is not None else None,
        "created_at":       _dt(r.created_at),
    }


@router.post("/run")
def run_backtest_endpoint(req: BacktestRequest):
    """
    Run a backtest and save the result to the database.
    Fetches candles + 200 warm-up bars automatically.
    Typical runtime: 5–15s for 300 candles.
    """
    logger.info("Backtest: %s %s %d candles", req.symbol, req.timeframe, req.candles)

    try:
        report = run_backtest(req.symbol, req.timeframe, req.candles)
    except Exception as exc:
        logger.error("Backtest failed: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "detail": type(exc).__name__},
        )

    try:
        with get_db() as db:
            result = BacktestResult(
                symbol=report.symbol,
                timeframe=report.timeframe,
                start_date=report.start_date,
                end_date=report.end_date,
                total_trades=report.total_trades,
                winning_trades=report.winning_trades,
                losing_trades=report.losing_trades,
                win_rate=report.win_rate,
                total_return_pct=report.total_return_pct,
                max_drawdown_pct=report.max_drawdown_pct,
                sharpe_ratio=report.sharpe_ratio,
                avg_win_pct=report.avg_win_pct,
                avg_loss_pct=report.avg_loss_pct,
            )
            db.add(result)
            db.flush()
            db.refresh(result)
            return JSONResponse(content=_result_to_dict(result))
    except Exception as exc:
        logger.error("Failed to save backtest: %s", exc, exc_info=True)
        # Return the report data even if DB save fails
        return JSONResponse(content={
            "id": -1,
            "symbol":           report.symbol,
            "timeframe":        report.timeframe,
            "start_date":       report.start_date.isoformat(),
            "end_date":         report.end_date.isoformat(),
            "total_trades":     report.total_trades,
            "winning_trades":   report.winning_trades,
            "losing_trades":    report.losing_trades,
            "win_rate":         report.win_rate,
            "total_return_pct": report.total_return_pct,
            "max_drawdown_pct": report.max_drawdown_pct,
            "sharpe_ratio":     report.sharpe_ratio,
            "avg_win_pct":      report.avg_win_pct,
            "avg_loss_pct":     report.avg_loss_pct,
            "created_at":       datetime.utcnow().isoformat(),
            "_note":            "DB save failed: " + str(exc),
        })


@router.get("/")
def list_backtests(limit: int = 20):
    try:
        with get_db() as db:
            rows = (
                db.query(BacktestResult)
                .order_by(BacktestResult.created_at.desc())
                .limit(limit)
                .all()
            )
            return JSONResponse(content=[_result_to_dict(r) for r in rows])
    except Exception as exc:
        logger.error("list_backtests failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
