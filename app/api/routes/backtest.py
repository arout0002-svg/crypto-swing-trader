"""API routes for backtesting."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import BacktestResult
from app.trading.backtester import run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    candles: int = 500


class BacktestOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    total_return_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    sharpe_ratio: Optional[float]
    avg_win_pct: Optional[float]
    avg_loss_pct: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/run", response_model=BacktestOut)
def run_backtest_endpoint(req: BacktestRequest):
    """
    Run a backtest and save the result to the database.
    This may take 30–60 seconds for 500 candles.
    """
    logger.info("Backtest requested: %s %s %d candles", req.symbol, req.timeframe, req.candles)
    try:
        report = run_backtest(req.symbol, req.timeframe, req.candles)
    except Exception as exc:
        logger.error("Backtest failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

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
        return result


@router.get("/", response_model=list[BacktestOut])
def list_backtests(limit: int = 20):
    with get_db() as db:
        return (
            db.query(BacktestResult)
            .order_by(BacktestResult.created_at.desc())
            .limit(limit)
            .all()
        )
