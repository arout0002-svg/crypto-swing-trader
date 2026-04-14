"""
Risk management — calculates position size, stop loss, and target.

Formula:
    Risk Amount     = Total Capital × Risk %
    Stop Loss Price = Entry × (1 - SL%)   for BUY
                    = Entry × (1 + SL%)   for SELL
    Target Price    = Entry × (1 + Target%) for BUY
                    = Entry × (1 - Target%) for SELL
    Position Size   = Risk Amount / Stop Loss %
"""
from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings


@dataclass
class TradeSetup:
    """Complete trade setup with all risk parameters."""
    symbol: str
    signal_type: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    target: float
    position_size_inr: float         # INR value of position
    units: float                     # number of coins
    risk_amount_inr: float           # INR at risk
    risk_reward_ratio: float
    potential_profit_inr: float
    potential_loss_inr: float

    def format_alert(self) -> str:
        """Format the trade setup as a human-readable alert message."""
        emoji = "🟢 BUY" if self.signal_type == "BUY" else "🔴 SELL/SHORT"
        return (
            f"🚀 {self.symbol} SIGNAL\n"
            f"Action: {emoji}\n"
            f"Entry:         ₹{self.entry_price:,.2f}\n"
            f"Stop Loss:     ₹{self.stop_loss:,.2f}\n"
            f"Target:        ₹{self.target:,.2f}\n"
            f"Position Size: ₹{self.position_size_inr:,.0f}\n"
            f"Risk Amount:   ₹{self.risk_amount_inr:,.0f}\n"
            f"R:R Ratio:     1:{self.risk_reward_ratio:.1f}\n"
            f"Units:         {self.units:.6f}"
        )


def calculate_trade_setup(
    symbol: str,
    signal_type: Literal["BUY", "SELL"],
    entry_price: float,
    sl_pct: float | None = None,
    target_pct: float | None = None,
) -> TradeSetup:
    """
    Calculate a complete trade setup for the given entry price and signal type.

    Args:
        symbol:      Trading pair (e.g. BTC/USDT)
        signal_type: BUY or SELL
        entry_price: Current close price
        sl_pct:      Stop loss % (defaults to config value)
        target_pct:  Take profit % (defaults to config value)
    """
    cfg = get_settings()
    sl_pct     = sl_pct     or cfg.STOP_LOSS_PCT
    target_pct = target_pct or cfg.TARGET_PCT

    risk_amount = cfg.TOTAL_CAPITAL * (cfg.RISK_PER_TRADE_PCT / 100)

    if signal_type == "BUY":
        stop_loss = entry_price * (1 - sl_pct / 100)
        target    = entry_price * (1 + target_pct / 100)
    else:  # SELL / SHORT
        stop_loss = entry_price * (1 + sl_pct / 100)
        target    = entry_price * (1 - target_pct / 100)

    sl_distance_pct  = abs(entry_price - stop_loss) / entry_price
    tgt_distance_pct = abs(target - entry_price)     / entry_price

    # Position size so that a stop-loss hit = risk_amount loss
    position_size_inr = risk_amount / sl_distance_pct
    # Cap at total capital
    position_size_inr = min(position_size_inr, cfg.TOTAL_CAPITAL)

    units = position_size_inr / entry_price

    rr_ratio        = tgt_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0
    potential_profit = position_size_inr * tgt_distance_pct
    potential_loss   = position_size_inr * sl_distance_pct

    return TradeSetup(
        symbol=symbol,
        signal_type=signal_type,
        entry_price=round(entry_price, 8),
        stop_loss=round(stop_loss, 8),
        target=round(target, 8),
        position_size_inr=round(position_size_inr, 2),
        units=round(units, 8),
        risk_amount_inr=round(risk_amount, 2),
        risk_reward_ratio=round(rr_ratio, 2),
        potential_profit_inr=round(potential_profit, 2),
        potential_loss_inr=round(potential_loss, 2),
    )
