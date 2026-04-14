"""
AI confirmation layer — validates trading signals using an LLM.

Supports:
  - Groq (free, fast)   → AI_PROVIDER=groq
  - OpenAI              → AI_PROVIDER=openai
  - Disabled            → AI_PROVIDER=disabled  (returns confidence=100, decision=signal)

Only signals with confidence >= AI_CONFIDENCE_THRESHOLD are acted upon.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import get_settings
from app.trading.strategy import StrategySignal

logger = logging.getLogger(__name__)
settings = get_settings()

_SYSTEM_PROMPT = """You are an expert quantitative crypto trader.
Analyze the given technical indicator values and validate whether the trade signal is high-probability.

Respond ONLY with valid JSON:
{
  "decision": "BUY" | "SELL" | "HOLD",
  "confidence": <integer 0-100>,
  "reasoning": "<one concise sentence>"
}

Rules:
- confidence >= 80: Very strong signal, all indicators strongly aligned
- confidence 70-79: Good signal, most indicators aligned
- confidence 50-69: Weak signal, mixed indicators
- confidence < 50: Poor signal, contradicting indicators
- If you are uncertain, return HOLD with confidence 40
- NEVER return markdown, ONLY raw JSON
"""


@dataclass
class AIResult:
    decision: str           # BUY | SELL | HOLD
    confidence: int         # 0–100
    reasoning: str
    provider: str           # "groq" | "openai" | "disabled"


def analyze_signal(signal: StrategySignal) -> AIResult:
    """
    Send the signal to the AI for confirmation.
    Returns AIResult with decision, confidence, and reasoning.
    """
    provider = settings.AI_PROVIDER.lower()

    if provider == "disabled":
        return AIResult(
            decision=signal.signal_type,
            confidence=85,
            reasoning="AI filter disabled — auto-approved.",
            provider="disabled",
        )

    prompt = _build_prompt(signal)

    try:
        if provider == "groq":
            return _call_groq(prompt, signal.signal_type)
        elif provider == "openai":
            return _call_openai(prompt, signal.signal_type)
        else:
            logger.warning("Unknown AI_PROVIDER '%s' — skipping AI filter", provider)
            return AIResult(
                decision=signal.signal_type,
                confidence=75,
                reasoning=f"Unknown provider '{provider}' — defaulting to signal.",
                provider=provider,
            )
    except Exception as exc:
        logger.error("AI filter failed: %s", exc)
        return AIResult(
            decision="HOLD",
            confidence=0,
            reasoning=f"AI error: {exc}",
            provider=provider,
        )


def _build_prompt(signal: StrategySignal) -> str:
    direction = "above" if signal.close_price > signal.ema200 else "below"
    macd_status = (
        "bullish crossover" if signal.macd > signal.macd_signal_val
        else "bearish crossover" if signal.macd < signal.macd_signal_val
        else "no crossover"
    )
    return (
        f"Symbol: {signal.symbol} | Timeframe: {signal.timeframe}\n"
        f"Signal: {signal.signal_type}\n\n"
        f"Indicator Values:\n"
        f"  Close Price:   {signal.close_price:.4f}\n"
        f"  EMA 200:       {signal.ema200:.4f} ({direction} EMA)\n"
        f"  RSI (14):      {signal.rsi:.2f}\n"
        f"  MACD:          {signal.macd:.6f}\n"
        f"  MACD Signal:   {signal.macd_signal_val:.6f}\n"
        f"  MACD Hist:     {signal.macd_hist:.6f} ({macd_status})\n"
        f"  Volume Ratio:  {signal.volume_ratio:.2f}x avg\n\n"
        f"Strategy Conditions Met:\n"
        + "\n".join(f"  ✓ {r}" for r in signal.reasons) + "\n\n"
        f"Validate this {signal.signal_type} signal. "
        f"Is this a high-probability trade setup? "
        f"Consider risk/reward and market context."
    )


def _parse_response(text: str, fallback_decision: str) -> AIResult:
    """Parse JSON from LLM response with repair fallback."""
    # Try direct parse
    try:
        data = json.loads(text.strip())
        return AIResult(
            decision=data.get("decision", fallback_decision).upper(),
            confidence=int(data.get("confidence", 50)),
            reasoning=data.get("reasoning", ""),
            provider="",
        )
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from text
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return AIResult(
                decision=data.get("decision", fallback_decision).upper(),
                confidence=int(data.get("confidence", 50)),
                reasoning=data.get("reasoning", ""),
                provider="",
            )
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse AI response: %s", text[:200])
    return AIResult(
        decision="HOLD",
        confidence=40,
        reasoning="AI response parsing failed",
        provider="",
    )


def _call_groq(prompt: str, fallback: str) -> AIResult:
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")

    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model": settings.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    logger.debug("Groq AI response: %s", content)
    result = _parse_response(content, fallback)
    result.provider = "groq"
    return result


def _call_openai(prompt: str, fallback: str) -> AIResult:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model": settings.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    result = _parse_response(content, fallback)
    result.provider = "openai"
    return result
