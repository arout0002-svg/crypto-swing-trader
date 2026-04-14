"""
Central configuration via Pydantic Settings.
All values come from environment variables / .env file.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "Crypto Swing Trader"
    DEBUG: bool = False
    PORT: int = 8001

    # ── Database (reuse existing PostgreSQL) ────────────────────────────────
    DATABASE_URL: str = "postgresql://arout@localhost:5432/copilot_db"

    # ── Trading ──────────────────────────────────────────────────────────────
    SYMBOLS: str = "BTC/USDT,ETH/USDT"          # comma-separated
    TIMEFRAMES: str = "15m,1h"                   # comma-separated
    TOTAL_CAPITAL: float = 100000.0              # INR
    RISK_PER_TRADE_PCT: float = 2.0              # 2% per trade
    STOP_LOSS_PCT: float = 2.0                   # 2% stop loss
    TARGET_PCT: float = 4.0                      # 4% minimum target
    CANDLES_LIMIT: int = 200
    SCHEDULE_INTERVAL_MINUTES: int = 10

    # ── RSI Thresholds ────────────────────────────────────────────────────────
    RSI_BUY_LOW: float = 32.0
    RSI_BUY_HIGH: float = 42.0
    RSI_SELL_LOW: float = 58.0
    RSI_SELL_HIGH: float = 68.0
    RSI_NEUTRAL_LOW: float = 45.0
    RSI_NEUTRAL_HIGH: float = 55.0

    # ── AI Filter ─────────────────────────────────────────────────────────────
    AI_PROVIDER: str = "groq"                    # "openai" | "groq" | "disabled"
    AI_CONFIDENCE_THRESHOLD: int = 70            # min confidence to send alert
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # ── Exchange ──────────────────────────────────────────────────────────────
    EXCHANGE: str = "binance"
    BINANCE_API_KEY: Optional[str] = None        # optional — only for live trading
    BINANCE_SECRET: Optional[str] = None

    # ── Email (Gmail SMTP) ────────────────────────────────────────────────────
    EMAIL_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None              # your Gmail address
    SMTP_PASSWORD: Optional[str] = None          # Gmail app password
    ALERT_EMAIL_TO: Optional[str] = None         # recipient email

    # ── WhatsApp (Twilio) ─────────────────────────────────────────────────────
    WHATSAPP_ENABLED: bool = False
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM: Optional[str] = None            # whatsapp:+14155238886
    TWILIO_TO: Optional[str] = None              # whatsapp:+91XXXXXXXXXX

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.SYMBOLS.split(",")]

    @property
    def timeframe_list(self) -> list[str]:
        return [t.strip() for t in self.TIMEFRAMES.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
