"""
Scheduler — runs the full trading pipeline every N minutes.

Pipeline per run:
  1. Fetch OHLCV data for all symbols + timeframes
  2. Compute indicators
  3. Evaluate strategy
  4. Skip HOLD signals
  5. Deduplicate: skip if same symbol+type signal sent in last 2 hours
  6. Apply AI filter (if enabled)
  7. Skip if confidence < threshold
  8. Calculate risk/position sizing
  9. Persist signal to DB
  10. Send alerts (email + WhatsApp)
  11. Log bot run
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.ai.ai_filter import analyze_signal
from app.core.config import get_settings
from app.core.database import get_db
from app.models.db_models import BotRun, Signal
from app.notifications.notifier import send_all_alerts
from app.trading.backtester import run_backtest
from app.trading.data_fetcher import fetch_all_symbols
from app.trading.indicators import compute_indicators, get_latest_values
from app.trading.risk_manager import calculate_trade_setup
from app.trading.strategy import evaluate

logger = logging.getLogger(__name__)
settings = get_settings()

# WebSocket broadcast callback (set by main.py)
_broadcast_fn = None


def set_broadcast(fn):
    global _broadcast_fn
    _broadcast_fn = fn


def _broadcast(event: dict):
    if _broadcast_fn:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_broadcast_fn(event))
        except Exception as exc:
            logger.debug("Broadcast failed: %s", exc)


def _is_duplicate(symbol: str, signal_type: str, hours: int = 2) -> bool:
    """Return True if the same signal was sent within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with get_db() as db:
        exists = (
            db.query(Signal)
            .filter(
                Signal.symbol == symbol,
                Signal.signal_type == signal_type,
                Signal.alert_sent == True,
                Signal.created_at >= cutoff,
            )
            .first()
        )
    return exists is not None


def run_pipeline() -> dict:
    """
    Execute one full trading scan.
    Returns a summary dict for the bot run log.
    """
    start_ms = time.time()
    signals_generated = 0
    alerts_sent = 0
    error_msg = None

    _broadcast({"type": "scan_started", "time": datetime.now(timezone.utc).isoformat()})

    try:
        all_data = fetch_all_symbols()

        for symbol, tf_data in all_data.items():
            for timeframe, df_raw in tf_data.items():
                try:
                    df = compute_indicators(df_raw)
                    ind = get_latest_values(df)
                    signal = evaluate(symbol, timeframe, ind)

                    if signal.signal_type == "HOLD":
                        logger.debug("HOLD: %s %s — skipping", symbol, timeframe)
                        continue

                    # Deduplication
                    if _is_duplicate(symbol, signal.signal_type):
                        logger.info(
                            "Duplicate %s %s signal — skipped (sent < 2h ago)",
                            symbol, signal.signal_type,
                        )
                        continue

                    # AI confirmation
                    ai = analyze_signal(signal)
                    logger.info(
                        "AI [%s]: %s %s → %s confidence=%d%%",
                        ai.provider, symbol, signal.signal_type,
                        ai.decision, ai.confidence,
                    )

                    if ai.confidence < settings.AI_CONFIDENCE_THRESHOLD:
                        logger.info(
                            "AI confidence %d%% < threshold %d%% — skipping %s %s",
                            ai.confidence, settings.AI_CONFIDENCE_THRESHOLD,
                            symbol, signal.signal_type,
                        )
                        # Save HOLD signal to DB (for history)
                        _save_signal(signal, ind, ai, alert_sent=False)
                        continue

                    # Risk management
                    setup = calculate_trade_setup(symbol, signal.signal_type, ind["close"])

                    # Persist signal
                    sig_db = _save_signal(signal, ind, ai, alert_sent=True)
                    signals_generated += 1

                    # Send alerts
                    n_sent = send_all_alerts(
                        setup=setup,
                        confidence=ai.confidence,
                        reasoning=ai.reasoning,
                        symbol=symbol,
                        timeframe=timeframe,
                        rsi=signal.rsi,
                        conditions=signal.reasons,
                    )
                    alerts_sent += n_sent

                    # Broadcast to WebSocket clients
                    _broadcast({
                        "type": "new_signal",
                        "data": {
                            "id": sig_db.id if sig_db else None,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "signal_type": signal.signal_type,
                            "entry_price": setup.entry_price,
                            "stop_loss": setup.stop_loss,
                            "target": setup.target,
                            "position_size_inr": setup.position_size_inr,
                            "confidence": ai.confidence,
                            "reasoning": ai.reasoning,
                            "rsi": signal.rsi,
                        },
                    })

                except Exception as exc:
                    logger.error("Error processing %s %s: %s", symbol, timeframe, exc, exc_info=True)

    except Exception as exc:
        error_msg = str(exc)
        logger.error("Pipeline error: %s", exc, exc_info=True)

    duration_ms = int((time.time() - start_ms) * 1000)

    # Log bot run
    with get_db() as db:
        run = BotRun(
            symbols_checked=",".join(settings.symbol_list),
            signals_generated=signals_generated,
            alerts_sent=alerts_sent,
            duration_ms=duration_ms,
            status="ERROR" if error_msg else "SUCCESS",
            error=error_msg,
        )
        db.add(run)

    summary = {
        "signals_generated": signals_generated,
        "alerts_sent": alerts_sent,
        "duration_ms": duration_ms,
        "status": "ERROR" if error_msg else "SUCCESS",
    }

    _broadcast({
        "type": "scan_complete",
        "data": summary,
        "time": datetime.now(timezone.utc).isoformat(),
    })

    logger.info(
        "Pipeline complete: signals=%d alerts=%d duration=%dms",
        signals_generated, alerts_sent, duration_ms,
    )
    return summary


def _save_signal(signal, ind: dict, ai, alert_sent: bool) -> Signal:
    """Persist a signal to the database and return the ORM object."""
    with get_db() as db:
        sig = Signal(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            signal_type=signal.signal_type,
            close_price=ind["close"],
            ema200=ind["ema200"],
            rsi=ind["rsi"],
            macd=ind["macd"],
            macd_signal=ind["macd_signal"],
            macd_hist=ind["macd_hist"],
            volume_ratio=ind["vol_ratio"],
            ai_confidence=ai.confidence,
            ai_reasoning=ai.reasoning,
            ai_decision=ai.decision,
            alert_sent=alert_sent,
        )
        db.add(sig)
        db.flush()
        db.refresh(sig)
        return sig


# ── Scheduler singleton ───────────────────────────────────────────────────────

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=settings.SCHEDULE_INTERVAL_MINUTES),
        id="trading_scan",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — running every %d minutes",
        settings.SCHEDULE_INTERVAL_MINUTES,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_next_run() -> str | None:
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("trading_scan")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    return None


def trigger_now() -> dict:
    """Manually trigger the pipeline immediately."""
    logger.info("Manual pipeline trigger requested")
    return run_pipeline()
