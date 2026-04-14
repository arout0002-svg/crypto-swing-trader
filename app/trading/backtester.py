"""
Backtesting module — runs the swing trading strategy on historical data.

Simulates BUY/SELL signals on historical candles and tracks trade outcomes.
Reports: total return, win rate, max drawdown, Sharpe ratio.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from app.core.config import get_settings
from app.trading.data_fetcher import fetch_ohlcv
from app.trading.indicators import compute_indicators, get_latest_values
from app.trading.strategy import evaluate
from app.trading.risk_manager import calculate_trade_setup

logger = logging.getLogger(__name__)
settings = get_settings()


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
    outcome: Optional[str] = None    # WIN | LOSS | STOPPED
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
            f"═══════════════════════════════════════\n"
            f"  BACKTEST RESULTS: {self.symbol} ({self.timeframe})\n"
            f"  Period: {self.start_date.date()} → {self.end_date.date()}\n"
            f"═══════════════════════════════════════\n"
            f"  Total Trades:    {self.total_trades}\n"
            f"  Winning:         {self.winning_trades} ({self.win_rate:.1f}%)\n"
            f"  Losing:          {self.losing_trades}\n"
            f"  Total Return:    {self.total_return_pct:+.2f}%\n"
            f"  Max Drawdown:    {self.max_drawdown_pct:.2f}%\n"
            f"  Sharpe Ratio:    {self.sharpe_ratio:.2f}\n"
            f"  Avg Win:         {self.avg_win_pct:+.2f}%\n"
            f"  Avg Loss:        {self.avg_loss_pct:+.2f}%\n"
            f"═══════════════════════════════════════"
        )


def run_backtest(
    symbol: str,
    timeframe: str = "1h",
    candles: int = 500,
) -> BacktestReport:
    """
    Run a backtest for the given symbol and timeframe.

    Uses a walk-forward approach:
    - Compute indicators on each slice of data
    - When a BUY/SELL signal fires, simulate the trade
    - Exit when price hits stop loss or target
    """
    logger.info("Starting backtest: %s %s (%d candles)", symbol, timeframe, candles)

    # Fetch more candles for warm-up
    df_raw = fetch_ohlcv(symbol, timeframe, limit=candles)
    df = compute_indicators(df_raw)
    df = df.reset_index()

    trades: list[BacktestTrade] = []
    equity_curve: list[float] = [100.0]  # start at 100%
    capital = 100.0

    open_trade: Optional[BacktestTrade] = None
    last_signal_type: Optional[str] = None

    for i in range(2, len(df)):
        row = df.iloc[i]
        close = float(row["close"])

        # ── Manage open trade ───────────────────────────────────────────────
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
                exit_price = open_trade.target if hit_tp else open_trade.stop_loss
                if open_trade.signal_type == "BUY":
                    pnl_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price * 100
                else:
                    pnl_pct = (open_trade.entry_price - exit_price) / open_trade.entry_price * 100

                open_trade.exit_price = exit_price
                open_trade.exit_idx = i
                open_trade.pnl_pct = round(pnl_pct, 4)
                open_trade.outcome = "WIN" if hit_tp else "LOSS"

                capital *= (1 + pnl_pct / 100)
                equity_curve.append(round(capital, 4))
                trades.append(open_trade)
                open_trade = None
                last_signal_type = None

            continue  # Don't check for new signals while in a trade

        # ── Check for new signal ────────────────────────────────────────────
        slice_df = df.iloc[:i+1].copy()
        slice_df.set_index("timestamp", inplace=True)

        ind = get_latest_values(slice_df)
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

    # ── Close any open trade at end of data ─────────────────────────────────
    if open_trade is not None:
        last_close = float(df.iloc[-1]["close"])
        if open_trade.signal_type == "BUY":
            pnl_pct = (last_close - open_trade.entry_price) / open_trade.entry_price * 100
        else:
            pnl_pct = (open_trade.entry_price - last_close) / open_trade.entry_price * 100
        open_trade.exit_price = last_close
        open_trade.exit_idx = len(df) - 1
        open_trade.pnl_pct = round(pnl_pct, 4)
        open_trade.outcome = "WIN" if pnl_pct > 0 else "LOSS"
        capital *= (1 + pnl_pct / 100)
        trades.append(open_trade)

    # ── Calculate metrics ────────────────────────────────────────────────────
    total = len(trades)
    winners = [t for t in trades if t.outcome == "WIN"]
    losers  = [t for t in trades if t.outcome == "LOSS"]

    win_rate     = (len(winners) / total * 100) if total > 0 else 0.0
    total_return = capital - 100.0
    avg_win      = sum(t.pnl_pct for t in winners) / len(winners) if winners else 0.0
    avg_loss     = sum(t.pnl_pct for t in losers)  / len(losers)  if losers  else 0.0

    # Max drawdown
    peak     = equity_curve[0]
    max_dd   = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd   = (peak - v) / peak * 100
        max_dd = max(max_dd, dd)

    # Sharpe ratio (annualised, assuming ~6 trades/month on 1h)
    if total > 1:
        returns = pd.Series([t.pnl_pct for t in trades])
        sharpe = (returns.mean() / returns.std()) * (total ** 0.5) if returns.std() > 0 else 0.0
    else:
        sharpe = 0.0

    report = BacktestReport(
        symbol=symbol,
        timeframe=timeframe,
        start_date=df.iloc[0]["timestamp"].to_pydatetime(),
        end_date=df.iloc[-1]["timestamp"].to_pydatetime(),
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
