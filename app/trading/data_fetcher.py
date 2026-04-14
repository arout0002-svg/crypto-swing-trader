"""
Data fetcher — connects to Binance via ccxt and returns OHLCV DataFrames.
Works without API keys for public market data (read-only).
"""
import logging
import time
from typing import Optional

import ccxt
import pandas as pd

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_exchange() -> ccxt.Exchange:
    """Create a ccxt Binance exchange instance."""
    params: dict = {
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
    if settings.BINANCE_API_KEY and settings.BINANCE_SECRET:
        params["apiKey"] = settings.BINANCE_API_KEY
        params["secret"] = settings.BINANCE_SECRET
    return ccxt.binance(params)


# Module-level singleton — reuse the same connection
_exchange: Optional[ccxt.Exchange] = None


def get_exchange() -> ccxt.Exchange:
    global _exchange
    if _exchange is None:
        _exchange = _build_exchange()
    return _exchange


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 200,
    retries: int = 3,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Binance.

    Returns a DataFrame with columns:
        timestamp, open, high, low, close, volume
    Indexed by timestamp (UTC).
    """
    exchange = get_exchange()
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not raw:
                raise ValueError(f"Empty OHLCV response for {symbol} {timeframe}")

            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)

            logger.debug(
                "Fetched %d candles for %s %s (last: %s)",
                len(df), symbol, timeframe, df.index[-1],
            )
            return df

        except ccxt.NetworkError as exc:
            last_exc = exc
            logger.warning(
                "Network error fetching %s %s (attempt %d/%d): %s",
                symbol, timeframe, attempt, retries, exc,
            )
            time.sleep(2 ** attempt)

        except ccxt.ExchangeError as exc:
            logger.error("Exchange error for %s %s: %s", symbol, timeframe, exc)
            raise

    raise RuntimeError(
        f"Failed to fetch {symbol} {timeframe} after {retries} retries"
    ) from last_exc


def fetch_current_price(symbol: str) -> float:
    """Fetch the latest ticker price for a symbol."""
    try:
        ticker = get_exchange().fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as exc:
        logger.error("Failed to fetch price for %s: %s", symbol, exc)
        raise


def fetch_all_symbols() -> dict[str, dict[str, pd.DataFrame]]:
    """
    Fetch OHLCV data for all configured symbols and timeframes.

    Returns: {symbol: {timeframe: df}}
    """
    result: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in settings.symbol_list:
        result[symbol] = {}
        for timeframe in settings.timeframe_list:
            try:
                result[symbol][timeframe] = fetch_ohlcv(
                    symbol, timeframe, limit=settings.CANDLES_LIMIT
                )
            except Exception as exc:
                logger.error(
                    "Skipping %s %s due to error: %s", symbol, timeframe, exc
                )
    return result
