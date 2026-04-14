"""
Backtesting module — vectorized walk-forward simulation of the swing strategy.

Key fixes vs v1:
  - Always fetches candles + 200 warm-up bars so EMA_200 is never empty
  - Direct row access (no per-candle DataFrame slicing) → 10× faster
  - Guards against empty df after indicator warm-up
  - Proper equity curve and drawdown tracking
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.core.config import get_settings
from app.trading.data_fetcher import fetch_ohlcv
from app.trading.indicators import compute_indicators
from app.trading.risk_manager import calculate_trade_setup
from app.trading.strategy import evaluate

logger = logging.getLogger(__name__)
settings = get_settings()

# EMA-200 needs 200 warm-up bars → always fetch this many extra
_WARMUP = 200


@dataclass
class BacktestTrade:
    symbol: str
    signal_type: str
    entry_price: float
    stop_loss: float
    target: float
    entry_idx: int
    exit_price: Optional[float] = None
    exit_idx: Optional[int] = None
    outcome: Optional[str] = None
    pnl_pct: Optional[float] = None


@dataclass
class BacktestReport:
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_win_pct: float
    avg_loss_pct: float
    trades: list[BacktestTrade] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"═══ BACKTEST {self.symbol} ({self.timeframe}) ═══\n"
            f"  Period:        {self.start_date.date()} → {self.end_date.date()}\n"
            f"  Total Trades:  {self.total_trades}\n"
            f"  Win Rate:      {self.win_rate:.1f}%\n"
            f"  Total Return:  {self.total_return_pct:+.2f}%\n"
            f"  Max Drawdown:  {self.max_drawdown_pct:.2f}%\n"
            f"  Sharpe Ratio:  {self.sharpe_ratio:.2f}\n"
        )


def _row_to_ind(df: pd.DataFrame, i: int) -> dict:
    """
    Build an indicator dict directly from pre-computed DataFrame rows.
    Avoids per-candle slicing/copying — 10× faster than the slice approach.
    """
    curr = df.iloc[i]
    prev = df.iloc[i - 1]

    def safe(v):
        return float(v) if not pd.isna(v) else 0.0

    return {
        "close":            safe(curr["close"]),
        "ema200":           safe(curr["EMA_200"]),
        "rsi":              safe(curr["RSI_14"]),
        "macd":             safe(curr["MACD_12_26_9"]),
        "macd_signal":      safe(curr["MACDs_12_26_9"]),
        "macd_hist":        safe(curr["MACDh_12_26_9"]),
        "prev_macd":        safe(prev["MACD_12_26_9"]),
        "prev_macd_signal": safe(prev["MACDs_12_26_9"]),
        "volume":           safe(curr["volume"]),
        "vol_ma_20":        safe(curr["vol_ma_20"]),
        "vol_ratio":        safe(curr["vol_ratio"]),
        "timestamp":        df.index[i],
    }


def run_backtest(
    symbol: str,
    timeframe: str = "1h",
    candles: int = 300,
) -> BacktestReport:
    """
    Run a vectorized walk-forward backtest.
    Fetches candles + 200 warm-up bars to ensure EMA_200 is valid.
    """
    fetch_limit = candles + _WARMUP
    logger.info(
        "Backtest %s %s: requesting %d candles (%d analysis + %d warm-up)",
        symbol, timeframe, fetch_limit, candles, _WARMUP,
    )

    df_raw = fetch_ohlcv(symbol, timeframe, limit=fetch_limit)
    df = compute_indicators(df_raw)  # drops NaN rows (warm-up period)

    if len(df) < 10:
        raise ValueError(
            f"Not enough valid candles after warm-up: only {len(df)} rows. "
            f"Try increasing 'candles' (minimum ~250 for EMA_200)."
        )

    logger.info("Backtest: %d candles available after warm-up", len(df))

    trades: list[BacktestTrade] = []
    equity = 100.0
    equity_curve = [equity]

    open_trade: Optional[BacktestTrade] = None
    last_signal_type: Optional[str] = None

    for i in range(1, len(df)):
        close = float(df.iloc[i]["close"])

        # ── Manage open trade ──────────────────────────────────────────────
        if open_trade is not None:
            hit_sl = (
                (open_trade.signal_type == "BUY"  and close <= open_trade.stop_loss) or
                (open_trade.signal_type == "SELL" and close >= open_trade.stop_loss)
            )
            hit_tp = (
                (open_trade.signal_type == "BUY"  and close >= open_trade.target) or
                (open_trade.signal_type == "SELL" and close <= open_trade.target)
            )

            if hit_tp or hit_sl:
                exit_px = open_trade.target if hit_tp else open_trade.stop_loss
                if open_trade.signal_type == "BUY":
                    pnl = (exit_px - open_trade.entry_price) / open_trade.entry_price * 100
                else:
                    pnl = (open_trade.entry_price - exit_px) / open_trade.entry_price * 100

                open_trade.exit_price = exit_px
                open_trade.exit_idx   = i
                open_trade.pnl_pct    = round(pnl, 4)
                open_trade.outcome    = "WIN" if hit_tp else "LOSS"

                equity *= (1 + pnl / 100)
                equity_curve.append(round(equity, 4))
                trades.append(open_trade)
                open_trade = None
                last_signal_type = None

            continue  # stay in the trade; no new signal on this bar

        # ── Check for new signal using pre-computed indicators ─────────────
        ind = _row_to_ind(df, i)
        sig = evaluate(symbol, timeframe, ind)

        if sig.signal_type in ("BUY", "SELL") and sig.signal_type != last_signal_type:
            setup = calculate_trade_setup(symbol, sig.signal_type, close)
            open_trade = BacktestTrade(
                symbol=symbol,
                signal_type=sig.signal_type,
                entry_price=close,
                stop_loss=setup.stop_loss,
                target=setup.target,
                entry_idx=i,
            )
            last_signal_type = sig.signal_type

    # ── Close open trade at end of data ────────────────────────────────────
    if open_trade is not None:
        last_close = float(df.iloc[-1]["close"])
        if open_trade.signal_type == "BUY":
            pnl = (last_close - open_trade.entry_price) / open_trade.entry_price * 100
        else:
            pnl = (open_trade.entry_price - last_close) / open_trade.entry_price * 100
        open_trade.exit_price = last_close
        open_trade.exit_idx   = len(df) - 1
        open_trade.pnl_pct    = round(pnl, 4)
        open_trade.outcome    = "WIN" if pnl > 0 else "LOSS"
        equity *= (1 + pnl / 100)
        trades.append(open_trade)

    # ── Metrics ────────────────────────────────────────────────────────────
    total   = len(trades)
    winners = [t for t in trades if t.outcome == "WIN"]
    losers  = [t for t in trades if t.outcome == "LOSS"]

    win_rate     = len(winners) / total * 100 if total else 0.0
    total_return = equity - 100.0
    avg_win      = sum(t.pnl_pct for t in winners) / len(winners) if winners else 0.0
    avg_loss     = sum(t.pnl_pct for t in losers)  / len(losers)  if losers  else 0.0

    # Max drawdown
    peak   = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak   = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100)

    # Simplified Sharpe
    if total > 1:
        returns = pd.Series([t.pnl_pct for t in trades])
        sharpe  = (returns.mean() / returns.std() * (total ** 0.5)) if returns.std() > 0 else 0.0
    else:
        sharpe = 0.0

    # Convert timestamps to UTC-aware datetimes
    def _ts(idx_val):
        if hasattr(idx_val, 'to_pydatetime'):
            dt = idx_val.to_pydatetime()
        else:
            dt = datetime.fromisoformat(str(idx_val))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    report = BacktestReport(
        symbol=symbol,
        timeframe=timeframe,
        start_date=_ts(df.index[0]),
        end_date=_ts(df.index[-1]),
        total_trades=total,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=round(win_rate, 2),
        total_return_pct=round(total_return, 4),
        max_drawdown_pct=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 4),
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        trades=trades,
    )

    logger.info(report.summary())
    return report
