"""Unit tests for the trading strategy logic."""
import pytest

from app.trading.strategy import evaluate


def _ind(close, ema200, rsi, macd, macd_s, prev_m, prev_s, vol_ratio):
    return {
        "close": close, "ema200": ema200, "rsi": rsi,
        "macd": macd, "macd_signal": macd_s,
        "prev_macd": prev_m, "prev_macd_signal": prev_s,
        "macd_hist": macd - macd_s,
        "volume": 1000, "vol_ma_20": 1000 / vol_ratio, "vol_ratio": vol_ratio,
        "timestamp": None,
    }


def test_buy_signal():
    ind = _ind(
        close=65000, ema200=60000, rsi=38,
        macd=0.01, macd_s=0.005,      # bullish: curr > signal
        prev_m=-0.005, prev_s=0.001,   # prev: macd < signal
        vol_ratio=1.5,
    )
    sig = evaluate("BTC/USDT", "1h", ind)
    assert sig.signal_type == "BUY"


def test_sell_signal():
    ind = _ind(
        close=55000, ema200=60000, rsi=63,
        macd=-0.01, macd_s=-0.005,     # bearish: curr < signal
        prev_m=0.005, prev_s=-0.001,   # prev: macd > signal
        vol_ratio=1.3,
    )
    sig = evaluate("BTC/USDT", "1h", ind)
    assert sig.signal_type == "SELL"


def test_hold_neutral_rsi():
    ind = _ind(close=65000, ema200=60000, rsi=50, macd=0.01, macd_s=0.005,
               prev_m=-0.005, prev_s=0.001, vol_ratio=1.5)
    sig = evaluate("BTC/USDT", "1h", ind)
    assert sig.signal_type == "HOLD"


def test_hold_near_ema():
    ind = _ind(close=60010, ema200=60000, rsi=38, macd=0.01, macd_s=0.005,
               prev_m=-0.005, prev_s=0.001, vol_ratio=1.5)
    sig = evaluate("BTC/USDT", "1h", ind)
    assert sig.signal_type == "HOLD"


def test_risk_manager():
    from app.trading.risk_manager import calculate_trade_setup
    setup = calculate_trade_setup("BTC/USDT", "BUY", 65000.0)
    assert setup.stop_loss < 65000
    assert setup.target > 65000
    assert setup.position_size_inr > 0
    assert setup.risk_reward_ratio >= 1.0
