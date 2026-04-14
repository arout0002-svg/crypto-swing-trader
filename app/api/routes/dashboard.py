"""Dashboard aggregate API — serves data for the UI charts."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import get_db, health_check
from app.models.db_models import BotRun, Signal, Trade
from app.scheduler.job_runner import get_next_run

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)
settings = get_settings()


@router.get("/summary")
def summary():
    """Main dashboard data — stats, recent signals, bot status."""
    with get_db() as db:
        last_run = db.query(BotRun).order_by(BotRun.run_at.desc()).first()
        recent_signals = (
            db.query(Signal)
            .filter(Signal.signal_type.in_(["BUY", "SELL"]))
            .order_by(Signal.created_at.desc())
            .limit(10)
            .all()
        )
        open_trades = db.query(Trade).filter(Trade.status == "OPEN").count()
        total_trades = db.query(Trade).filter(
            Trade.status.in_(["CLOSED_WIN", "CLOSED_LOSS", "STOPPED"])
        ).count()
        wins = db.query(Trade).filter(Trade.status == "CLOSED_WIN").count()
        total_pnl = db.query(Trade).with_entities(Trade.pnl_inr).filter(
            Trade.pnl_inr.isnot(None)
        ).all()
        total_pnl_val = round(sum(r[0] for r in total_pnl if r[0]), 2)

    return {
        "bot": {
            "status": "running",
            "last_run": last_run.run_at.isoformat() if last_run else None,
            "last_signals": last_run.signals_generated if last_run else 0,
            "next_run": get_next_run(),
        },
        "capital": {
            "total": settings.TOTAL_CAPITAL,
            "risk_per_trade_pct": settings.RISK_PER_TRADE_PCT,
        },
        "trades": {
            "open": open_trades,
            "total_closed": total_trades,
            "wins": wins,
            "win_rate": round(wins / total_trades * 100, 1) if total_trades else 0,
            "total_pnl_inr": total_pnl_val,
        },
        "signals": [
            {
                "id": s.id,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "signal_type": s.signal_type,
                "close_price": float(s.close_price) if s.close_price else None,
                "rsi": float(s.rsi) if s.rsi else None,
                "ai_confidence": s.ai_confidence,
                "ai_reasoning": s.ai_reasoning,
                "created_at": s.created_at.isoformat(),
            }
            for s in recent_signals
        ],
        "db_healthy": health_check(),
    }


@router.get("/equity-curve")
def equity_curve():
    """Return closed trade P&L over time for the equity curve chart."""
    since = datetime.now(timezone.utc) - timedelta(days=90)
    with get_db() as db:
        trades = (
            db.query(Trade)
            .filter(
                Trade.status.in_(["CLOSED_WIN", "CLOSED_LOSS", "STOPPED"]),
                Trade.closed_at >= since,
            )
            .order_by(Trade.closed_at)
            .all()
        )

    cumulative = 0.0
    points = []
    for t in trades:
        cumulative += t.pnl_inr or 0
        points.append({
            "date": t.closed_at.date().isoformat() if t.closed_at else None,
            "pnl_inr": round(t.pnl_inr or 0, 2),
            "cumulative_inr": round(cumulative, 2),
            "symbol": t.symbol,
        })
    return {"data": points, "total_pnl_inr": round(cumulative, 2)}


@router.get("/signal-history")
def signal_history(days: int = 30):
    """Signal count per day for chart."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with get_db() as db:
        signals = (
            db.query(Signal)
            .filter(Signal.created_at >= since)
            .order_by(Signal.created_at)
            .all()
        )

    by_date: dict = {}
    for s in signals:
        d = s.created_at.date().isoformat()
        if d not in by_date:
            by_date[d] = {"date": d, "BUY": 0, "SELL": 0, "HOLD": 0}
        by_date[d][s.signal_type] = by_date[d].get(s.signal_type, 0) + 1

    return {"data": sorted(by_date.values(), key=lambda x: x["date"])}


@router.get("/bot-runs")
def bot_runs(limit: int = 20):
    """Recent bot run history."""
    with get_db() as db:
        runs = (
            db.query(BotRun)
            .order_by(BotRun.run_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "run_at": r.run_at.isoformat(),
                "signals_generated": r.signals_generated,
                "alerts_sent": r.alerts_sent,
                "duration_ms": r.duration_ms,
                "status": r.status,
                "error": r.error,
            }
            for r in runs
        ]
