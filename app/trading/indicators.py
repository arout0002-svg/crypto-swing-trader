"""
Technical indicators using the `ta` library (pure pandas, no C/numba deps).

Adds columns to the DataFrame:
    EMA_200      — 200-period Exponential Moving Average
    RSI_14       — 14-period RSI
    MACD_12_26_9 — MACD line
    MACDs_12_26_9— MACD signal line
    MACDh_12_26_9— MACD histogram
    vol_ma_20    — 20-period volume simple moving average
    vol_ratio    — current volume / vol_ma_20
"""
import logging

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

logger = logging.getLogger(__name__)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all required indicators on a copy of the OHLCV DataFrame."""
    df = df.copy()

    # EMA 200
    df["EMA_200"] = EMAIndicator(close=df["close"], window=200).ema_indicator()

    # RSI 14
    df["RSI_14"] = RSIIndicator(close=df["close"], window=14).rsi()

    # MACD (12, 26, 9)
    macd_obj = MACD(
        close=df["close"],
        window_fast=12,
        window_slow=26,
        window_sign=9,
    )
    df["MACD_12_26_9"]  = macd_obj.macd()
    df["MACDs_12_26_9"] = macd_obj.macd_signal()
    df["MACDh_12_26_9"] = macd_obj.macd_diff()

    # Volume moving average (20 periods)
    df["vol_ma_20"] = df["volume"].rolling(window=20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma_20"].replace(0, float("nan"))

    # Drop warm-up rows
    required_cols = ["EMA_200", "RSI_14", "MACD_12_26_9", "MACDs_12_26_9"]
    before = len(df)
    df.dropna(subset=required_cols, inplace=True)
    dropped = before - len(df)
    if dropped:
        logger.debug("Dropped %d warm-up rows", dropped)

    return df


def get_latest_values(df: pd.DataFrame) -> dict:
    """Extract the latest indicator snapshot from the last two rows."""
    if len(df) < 2:
        raise ValueError("Need at least 2 rows to get indicator values")

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "close":            float(curr["close"]),
        "ema200":           float(curr["EMA_200"]),
        "rsi":              float(curr["RSI_14"]),
        "macd":             float(curr["MACD_12_26_9"]),
        "macd_signal":      float(curr["MACDs_12_26_9"]),
        "macd_hist":        float(curr["MACDh_12_26_9"]),
        "prev_macd":        float(prev["MACD_12_26_9"]),
        "prev_macd_signal": float(prev["MACDs_12_26_9"]),
        "volume":           float(curr["volume"]),
        "vol_ma_20":        float(curr["vol_ma_20"]) if not pd.isna(curr["vol_ma_20"]) else 0.0,
        "vol_ratio":        float(curr["vol_ratio"])  if not pd.isna(curr["vol_ratio"])  else 0.0,
        "timestamp":        df.index[-1],
    }
