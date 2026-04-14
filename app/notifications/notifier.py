"""
Alert notification system — sends trade signals via Email and WhatsApp.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import get_settings
from app.trading.risk_manager import TradeSetup

logger = logging.getLogger(__name__)
settings = get_settings()


def build_message(
    setup: TradeSetup,
    confidence: int,
    reasoning: str,
    symbol: str,
    timeframe: str,
    rsi: float,
    conditions: list[str],
) -> str:
    """Build a formatted alert message."""
    emoji = "🟢" if setup.signal_type == "BUY" else "🔴"
    lines = [
        f"{emoji} *{symbol} SIGNAL* ({timeframe})",
        f"",
        f"Action:        *{setup.signal_type}*",
        f"Entry Price:   ₹{setup.entry_price:,.4f}",
        f"Stop Loss:     ₹{setup.stop_loss:,.4f}",
        f"Target:        ₹{setup.target:,.4f}",
        f"Position Size: ₹{setup.position_size_inr:,.0f}",
        f"Risk Amount:   ₹{setup.risk_amount_inr:,.0f}",
        f"R:R Ratio:     1:{setup.risk_reward_ratio:.1f}",
        f"",
        f"📊 Indicators:",
        f"  RSI:         {rsi:.1f}",
        f"",
        f"🤖 AI Confidence: {confidence}%",
        f"Reason: {reasoning}",
        f"",
        f"✅ Conditions:",
    ]
    for c in conditions:
        lines.append(f"  • {c}")
    return "\n".join(lines)


def send_email(subject: str, body: str) -> bool:
    """Send an alert email via Gmail SMTP."""
    if not settings.EMAIL_ENABLED:
        logger.debug("Email alerts disabled — skipping")
        return False

    required = [settings.SMTP_USER, settings.SMTP_PASSWORD, settings.ALERT_EMAIL_TO]
    if not all(required):
        logger.warning("Email not configured — missing SMTP_USER/PASSWORD/ALERT_EMAIL_TO")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = settings.ALERT_EMAIL_TO

        # Plain text
        msg.attach(MIMEText(body, "plain"))

        # HTML version (basic formatting)
        html_body = body.replace("\n", "<br>").replace("*", "<b>").replace("*", "</b>")
        html = f"<html><body style='font-family:monospace'>{html_body}</body></html>"
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, settings.ALERT_EMAIL_TO, msg.as_string())

        logger.info("Email alert sent to %s", settings.ALERT_EMAIL_TO)
        return True

    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False


def send_whatsapp(body: str) -> bool:
    """Send an alert via Twilio WhatsApp API."""
    if not settings.WHATSAPP_ENABLED:
        logger.debug("WhatsApp alerts disabled — skipping")
        return False

    required = [
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
        settings.TWILIO_FROM,
        settings.TWILIO_TO,
    ]
    if not all(required):
        logger.warning("WhatsApp not configured — missing Twilio credentials")
        return False

    try:
        from twilio.rest import Client  # type: ignore
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_FROM,
            to=settings.TWILIO_TO,
        )
        logger.info("WhatsApp alert sent: SID=%s", message.sid)
        return True

    except ImportError:
        logger.error("twilio package not installed — pip install twilio")
        return False
    except Exception as exc:
        logger.error("Failed to send WhatsApp: %s", exc)
        return False


def send_all_alerts(
    setup: TradeSetup,
    confidence: int,
    reasoning: str,
    symbol: str,
    timeframe: str,
    rsi: float,
    conditions: list[str],
) -> int:
    """
    Send alerts via all enabled channels.
    Returns the number of successful sends.
    """
    msg = build_message(setup, confidence, reasoning, symbol, timeframe, rsi, conditions)
    subject = f"🚀 {symbol} {setup.signal_type} Signal — Confidence {confidence}%"

    sent = 0
    if send_email(subject, msg):
        sent += 1
    if send_whatsapp(msg):
        sent += 1

    # Always log the signal to console
    logger.info("\n" + "=" * 60 + "\n" + msg + "\n" + "=" * 60)
    return sent
