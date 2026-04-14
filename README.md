# Crypto Swing Trader — AI Signal Bot

A production-ready AI-assisted crypto swing trading system with real-time dashboard.

## Features

- **Technical Strategy**: EMA 200 trend filter + RSI pullback + MACD crossover + Volume confirmation
- **AI Signal Validation**: Groq/OpenAI confirms each signal with a confidence score (≥70% threshold)
- **Risk Management**: 2% risk per trade, auto-calculated position size / stop loss / target
- **Alerts**: Email (Gmail SMTP) + WhatsApp (Twilio)
- **Live Dashboard**: Real-time trading dashboard with WebSocket updates
- **Backtesting**: Historical strategy simulation with equity curve, win rate, Sharpe ratio
- **Database**: PostgreSQL (shared with AI Data Copilot) — stores all signals, trades, backtest results
- **CI/CD**: GitHub Actions → EC2 auto-deploy

## Quick Start

```bash
cd crypto-swing-trader
bash start.sh
```

Dashboard: http://localhost:8001  
API Docs: http://localhost:8001/docs

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `GROQ_API_KEY` | Yes (if using Groq) | Free at console.groq.com |
| `SYMBOLS` | No | Default: `BTC/USDT,ETH/USDT` |
| `AI_PROVIDER` | No | `groq` / `openai` / `disabled` |
| `EMAIL_ENABLED` | No | Set `true` + SMTP credentials |
| `WHATSAPP_ENABLED` | No | Set `true` + Twilio credentials |

## GitHub Secrets (for CI/CD)

| Secret | Description |
|---|---|
| `EC2_SSH_KEY` | Private SSH key for EC2 |
| `EC2_HOST` | EC2 public IP |
| `GROQ_API_KEY` | Groq API key |
| `DATABASE_URL` | Production DB URL |

## Strategy Logic

```
BUY  = close > EMA200  AND  RSI 32–42  AND  MACD bullish crossover  AND  volume > avg
SELL = close < EMA200  AND  RSI 58–68  AND  MACD bearish crossover  AND  volume > avg
HOLD = RSI 45–55 (neutral zone) OR price within 1% of EMA200
```

## Architecture

```
app/
├── main.py              # FastAPI + WebSocket + startup
├── core/
│   ├── config.py        # Settings (Pydantic)
│   └── database.py      # SQLAlchemy engine
├── trading/
│   ├── data_fetcher.py  # ccxt → Binance OHLCV
│   ├── indicators.py    # EMA/RSI/MACD/Volume (pandas_ta)
│   ├── strategy.py      # BUY/SELL/HOLD logic
│   ├── risk_manager.py  # Position sizing
│   └── backtester.py    # Historical simulation
├── ai/
│   └── ai_filter.py     # Groq/OpenAI signal validation
├── notifications/
│   └── notifier.py      # Email + WhatsApp alerts
├── scheduler/
│   └── job_runner.py    # APScheduler 10-min pipeline
├── models/
│   └── db_models.py     # SQLAlchemy ORM tables
└── api/routes/
    ├── signals.py       # Signal CRUD + manual scan
    ├── trades.py        # Trade journal
    ├── backtest.py      # Backtest runs
    └── dashboard.py     # Dashboard aggregates
```
