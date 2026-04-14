"""API routes for trade management."""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import Trade

router = APIRouter(prefix="/trades", tags=["trades"])
logger = logging.getLogger(__name__)


class TradeCreate(BaseModel):
    signal_id: Optional[int] = None
    symbol: str
    signal_type: str
    entry_price: float
    stop_loss: float
    target: float
    position_size_inr: float
    notes: Optional[str] = None


class TradeClose(BaseModel):
    exit_price: float
    notes: Optional[str] = None


class TradeOut(BaseModel):
    id: int
    signal_id: Optional[int]
    symbol: str
    signal_type: str
    entry_price: Optional[float]
    exit_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    position_size_inr: Optional[float]
    pnl_inr: Optional[float]
    pnl_pct: Optional[float]
    status: str
    notes: Optional[str]
    opened_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[TradeOut])
def list_trades(status: Optional[str] = None, limit: int = 50):
    with get_db() as db:
        q = db.query(Trade).order_by(Trade.opened_at.desc())
        if status:
            q = q.filter(Trade.status == status.upper())
        return q.limit(limit).all()


@router.post("/", response_model=TradeOut)
def create_trade(body: TradeCreate):
    """Manually record a trade."""
    with get_db() as db:
        trade = Trade(**body.model_dump())
        db.add(trade)
        db.flush()
        db.refresh(trade)
        return trade


@router.patch("/{trade_id}/close", response_model=TradeOut)
def close_trade(trade_id: int, body: TradeClose):
    """Mark a trade as closed and compute P&L."""
    with get_db() as db:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        if trade.status != "OPEN":
            raise HTTPException(status_code=400, detail="Trade already closed")

        trade.exit_price = body.exit_price
        trade.closed_at = datetime.now(timezone.utc)

        if trade.entry_price:
            if trade.signal_type == "BUY":
                pnl_pct = (body.exit_price - trade.entry_price) / trade.entry_price * 100
            else:
                pnl_pct = (trade.entry_price - body.exit_price) / trade.entry_price * 100
            trade.pnl_pct = round(pnl_pct, 4)
            if trade.position_size_inr:
                trade.pnl_inr = round(trade.position_size_inr * pnl_pct / 100, 2)
            trade.status = "CLOSED_WIN" if pnl_pct > 0 else "CLOSED_LOSS"

        if body.notes:
            trade.notes = body.notes

        db.flush()
        db.refresh(trade)
        return trade


@router.get("/performance")
def trade_performance():
    """Aggregate P&L performance metrics."""
    with get_db() as db:
        closed = db.query(Trade).filter(Trade.status.in_(["CLOSED_WIN", "CLOSED_LOSS", "STOPPED"])).all()
        if not closed:
            return {"message": "No closed trades yet"}

        wins   = [t for t in closed if t.status == "CLOSED_WIN"]
        losses = [t for t in closed if t.status != "CLOSED_WIN"]
        total_pnl = sum((t.pnl_inr or 0) for t in closed)
        win_rate  = len(wins) / len(closed) * 100 if closed else 0

        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_inr": round(total_pnl, 2),
            "avg_win_inr": round(sum((t.pnl_inr or 0) for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss_inr": round(sum((t.pnl_inr or 0) for t in losses) / len(losses), 2) if losses else 0,
        }
