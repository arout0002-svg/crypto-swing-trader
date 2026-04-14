"""
Swing trading strategy — evaluates indicator values and returns a signal.

BUY conditions (all must be true):
  1. close > EMA_200               (bullish trend)
  2. RSI between 32–42             (oversold pullback)
  3. MACD bullish crossover        (prev_macd < prev_signal, curr_macd > curr_signal)
  4. volume > 20-period average

SELL conditions (all must be true):
  1. close < EMA_200               (bearish trend)
  2. RSI between 58–68             (overbought)
  3. MACD bearish crossover        (prev_macd > prev_signal, curr_macd < curr_signal)
  4. volume > 20-period average

NO TRADE:
  - RSI between 45–55              (neutral zone)
  - price near EMA_200 (within 1%) (sideways)
"""
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SignalType = Literal["BUY", "SELL", "HOLD"]


@dataclass
class StrategySignal:
    """Output of the strategy evaluation."""
    signal_type: SignalType
    symbol: str
    timeframe: str

    # Indicator values
    close_price: float = 0.0
    ema200: float = 0.0
    rsi: float = 0.0
    macd: float = 0.0
    macd_signal_val: float = 0.0
    macd_hist: float = 0.0
    volume_ratio: float = 0.0

    # Human-readable conditions met
    reasons: list[str] = field(default_factory=list)
    reasons_failed: list[str] = field(default_factory=list)


def evaluate(
    symbol: str,
    timeframe: str,
    ind: dict,
) -> StrategySignal:
    """
    Evaluate indicator values against strategy rules.
    Returns a StrategySignal with BUY / SELL / HOLD.
    """
    close   = ind["close"]
    ema200  = ind["ema200"]
    rsi     = ind["rsi"]
    macd    = ind["macd"]
    macd_s  = ind["macd_signal"]
    prev_m  = ind["prev_macd"]
    prev_s  = ind["prev_macd_signal"]
    v_ratio = ind["vol_ratio"]

    cfg = settings

    # ── NO TRADE zone (early exit) ────────────────────────────────────────────
    if cfg.RSI_NEUTRAL_LOW <= rsi <= cfg.RSI_NEUTRAL_HIGH:
        return _signal("HOLD", symbol, timeframe, ind,
                       reasons=[f"RSI {rsi:.1f} in neutral zone ({cfg.RSI_NEUTRAL_LOW}–{cfg.RSI_NEUTRAL_HIGH})"])

    near_ema = abs(close - ema200) / ema200 < 0.01
    if near_ema:
        return _signal("HOLD", symbol, timeframe, ind,
                       reasons=[f"Price within 1% of EMA200 — sideways market"])

    # ── Condition checks ──────────────────────────────────────────────────────
    bullish_crossover = (prev_m < prev_s) and (macd > macd_s)
    bearish_crossover = (prev_m > prev_s) and (macd < macd_s)
    vol_above_avg     = v_ratio >= 1.0

    # ── BUY ───────────────────────────────────────────────────────────────────
    buy_conditions = {
        f"close ({close:.2f}) > EMA200 ({ema200:.2f})":         close > ema200,
        f"RSI {rsi:.1f} in buy zone ({cfg.RSI_BUY_LOW}–{cfg.RSI_BUY_HIGH})":
            cfg.RSI_BUY_LOW <= rsi <= cfg.RSI_BUY_HIGH,
        f"MACD bullish crossover (prev {prev_m:.4f}<{prev_s:.4f}, curr {macd:.4f}>{macd_s:.4f})":
            bullish_crossover,
        f"Volume ratio {v_ratio:.2f}x above average":           vol_above_avg,
    }

    # ── SELL ──────────────────────────────────────────────────────────────────
    sell_conditions = {
        f"close ({close:.2f}) < EMA200 ({ema200:.2f})":         close < ema200,
        f"RSI {rsi:.1f} in sell zone ({cfg.RSI_SELL_LOW}–{cfg.RSI_SELL_HIGH})":
            cfg.RSI_SELL_LOW <= rsi <= cfg.RSI_SELL_HIGH,
        f"MACD bearish crossover (prev {prev_m:.4f}>{prev_s:.4f}, curr {macd:.4f}<{macd_s:.4f})":
            bearish_crossover,
        f"Volume ratio {v_ratio:.2f}x above average":           vol_above_avg,
    }

    buy_met   = [k for k, v in buy_conditions.items() if v]
    buy_fail  = [k for k, v in buy_conditions.items() if not v]
    sell_met  = [k for k, v in sell_conditions.items() if v]
    sell_fail = [k for k, v in sell_conditions.items() if not v]

    if len(buy_fail) == 0:
        logger.info("BUY signal: %s %s — all %d conditions met", symbol, timeframe, len(buy_met))
        return _signal("BUY", symbol, timeframe, ind, reasons=buy_met)

    if len(sell_fail) == 0:
        logger.info("SELL signal: %s %s — all %d conditions met", symbol, timeframe, len(sell_met))
        return _signal("SELL", symbol, timeframe, ind, reasons=sell_met)

    # Partial — log what's missing
    best = buy_met if len(buy_met) >= len(sell_met) else sell_met
    best_fail = buy_fail if len(buy_met) >= len(sell_met) else sell_fail
    logger.debug(
        "HOLD: %s %s — %d/%d conditions met, missing: %s",
        symbol, timeframe,
        len(best), len(buy_conditions),
        " | ".join(best_fail),
    )
    return _signal("HOLD", symbol, timeframe, ind, reasons=best, reasons_failed=best_fail)


def _signal(
    sig_type: SignalType,
    symbol: str,
    timeframe: str,
    ind: dict,
    reasons: list[str],
    reasons_failed: Optional[list[str]] = None,
) -> StrategySignal:
    return StrategySignal(
        signal_type=sig_type,
        symbol=symbol,
        timeframe=timeframe,
        close_price=ind["close"],
        ema200=ind["ema200"],
        rsi=ind["rsi"],
        macd=ind["macd"],
        macd_signal_val=ind["macd_signal"],
        macd_hist=ind["macd_hist"],
        volume_ratio=ind["vol_ratio"],
        reasons=reasons,
        reasons_failed=reasons_failed or [],
    )
