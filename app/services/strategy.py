from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import numpy as np

from app.models import Candle, SignalType, Timeframe, TradeSignal


def _ema(values: List[float], period: int) -> np.ndarray:
    """
    Simple EMA implementation using numpy.
    Returns an array of the same length as `values`.
    """
    prices = np.array(values, dtype=float)
    if len(prices) < period:
        return np.full_like(prices, np.nan)

    ema_values = np.zeros_like(prices)
    k = 2 / (period + 1)

    # start EMA with simple average of first `period` values
    ema_values[period - 1] = prices[:period].mean()
    for i in range(period, len(prices)):
        ema_values[i] = prices[i] * k + ema_values[i - 1] * (1 - k)

    # leading values before we have enough data are NaN
    ema_values[: period - 1] = np.nan
    return ema_values


def _rsi(values: List[float], period: int = 14) -> np.ndarray:
    """
    Compute RSI using Wilder's smoothing.
    Returns an array of the same length as `values`.
    """
    prices = np.array(values, dtype=float)
    if len(prices) < period + 1:
        return np.full_like(prices, np.nan)

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.empty_like(prices)
    avg_loss = np.empty_like(prices)
    avg_gain[: period] = np.nan
    avg_loss[: period] = np.nan

    # initial averages
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()

    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    rs = np.divide(
        avg_gain,
        avg_loss,
        out=np.full_like(avg_gain, np.nan),
        where=avg_loss != 0,
    )
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi[: period] = np.nan
    return rsi


def _atr(candles: List[Candle], period: int = 14) -> np.ndarray:
    """
    Average True Range on the candle list.
    Returns an array aligned to `candles` length.
    """
    if len(candles) < period + 1:
        return np.full(len(candles), np.nan, dtype=float)

    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)

    trs = np.zeros_like(closes)
    for i in range(1, len(candles)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs[i] = tr

    atr = np.zeros_like(closes)
    atr[: period] = np.nan
    atr[period] = trs[1 : period + 1].mean()
    for i in range(period + 1, len(trs)):
        atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period

    return atr


def get_htf_trend(candles: List[Candle]) -> Optional[str]:
    """
    Compute higher-timeframe trend from candles using 50/200 EMA.
    Returns "up" if 50 EMA > 200 EMA, "down" otherwise, or None if not enough data.
    """
    if len(candles) < 210:
        return None
    closes = [c.close for c in candles]
    ema_short = _ema(closes, 50)
    ema_long = _ema(closes, 200)
    if np.isnan(ema_short[-1]) or np.isnan(ema_long[-1]):
        return None
    return "up" if ema_short[-1] > ema_long[-1] else "down"


def generate_simple_trend_signal(
    symbol: str,
    timeframe: Timeframe,
    candles: List[Candle],
    htf_trend: Optional[str] = None,
) -> TradeSignal:
    """
    Improved strategy:
    - Compute 50 EMA, 200 EMA, RSI, ATR on the given candles.
    - Uptrend (50 > 200): look for LONG_ENTRY / LONG_EXIT with RSI filter.
    - Downtrend (50 < 200): look for SHORT_ENTRY / SHORT_EXIT with RSI filter.
    - Optional multi-timeframe filter: if htf_trend is "up", only allow LONG_ENTRY
      (block SHORT_ENTRY). If htf_trend is "down", only allow SHORT_ENTRY (block LONG_ENTRY).
      EXIT signals are never blocked.
    """
    if len(candles) < 210:
        # not enough data for EMAs
        last = candles[-1]
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=SignalType.NO_TRADE,
            price=last.close,
            generated_at=datetime.utcnow(),
            reason="Not enough candles to compute EMAs",
        )

    closes = [c.close for c in candles]
    ema_short = _ema(closes, 50)
    ema_long = _ema(closes, 200)
    rsi = _rsi(closes, 14)
    atr = _atr(candles, 14)

    last = candles[-1]
    prev = candles[-2]

    ema_short_last = float(ema_short[-1])
    ema_long_last = float(ema_long[-1])
    ema_short_prev = float(ema_short[-2])
    rsi_last = float(rsi[-1])
    rsi_prev = float(rsi[-2]) if len(rsi) >= 2 else np.nan
    atr_last = float(atr[-1])
    atr_pct = atr_last / last.close * 100.0 if last.close else np.nan

    # Guard against NaN
    if (
        np.isnan(ema_short_last)
        or np.isnan(ema_long_last)
        or np.isnan(ema_short_prev)
        or np.isnan(rsi_last)
        or np.isnan(atr_last)
    ):
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=SignalType.NO_TRADE,
            price=last.close,
            generated_at=datetime.utcnow(),
            reason="Indicator values are not ready yet",
        )

    # Volatility filter: avoid dead markets and extreme spikes
    # Only trade when ATR is between 0.3% and 4% of price.
    if not (0.3 <= atr_pct <= 4.0):
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=SignalType.NO_TRADE,
            price=last.close,
            generated_at=datetime.utcnow(),
            reason=f"Volatility filter: ATR {atr_pct:.2f}% outside 0.3–4% band.",
            extra={
                "ema_short": ema_short_last,
                "ema_long": ema_long_last,
                "rsi": rsi_last,
                "rsi_prev": rsi_prev,
                "atr_pct": atr_pct,
            },
        )

    # Regime logic with RSI and both long/short directions
    # Long regime: short EMA above long EMA and RSI in a healthy range
    if ema_short_last > ema_long_last and 40 <= rsi_last <= 70:
        if prev.close <= ema_short_prev and last.close > ema_short_last and rsi_last > 50:
            signal = SignalType.LONG_ENTRY
            reason = (
                "Uptrend (50>200) with price closing above 50 EMA and RSI recovering above 50."
            )
        elif last.close < ema_short_last or rsi_last > 70 or rsi_last < 40:
            signal = SignalType.LONG_EXIT
            reason = "Exit long: price losing 50 EMA or RSI leaving healthy range."
        else:
            signal = SignalType.NO_TRADE
            reason = "Uptrend but entry/exit trigger not met."

    # Short regime: short EMA below long EMA and RSI in a healthy range
    elif ema_short_last < ema_long_last and 30 <= rsi_last <= 60:
        if prev.close >= ema_short_prev and last.close < ema_short_last and rsi_last < 50:
            signal = SignalType.SHORT_ENTRY
            reason = (
                "Downtrend (50<200) with price closing below 50 EMA and RSI dropping below 50."
            )
        elif last.close > ema_short_last or rsi_last < 30 or rsi_last > 60:
            signal = SignalType.SHORT_EXIT
            reason = "Exit short: price regaining 50 EMA or RSI leaving healthy range."
        else:
            signal = SignalType.NO_TRADE
            reason = "Downtrend but entry/exit trigger not met."

    else:
        signal = SignalType.NO_TRADE
        reason = "Trend or RSI filters not satisfied."

    # Multi-timeframe filter: don't take entries against the higher-timeframe trend.
    # EXIT signals are always allowed (you can always close a position).
    if htf_trend is not None and signal in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
        if signal == SignalType.LONG_ENTRY and htf_trend == "down":
            signal = SignalType.NO_TRADE
            reason = (
                "1h trend is down; long entry blocked by multi-timeframe filter. "
                "Trade with the higher timeframe."
            )
        elif signal == SignalType.SHORT_ENTRY and htf_trend == "up":
            signal = SignalType.NO_TRADE
            reason = (
                "1h trend is up; short entry blocked by multi-timeframe filter. "
                "Trade with the higher timeframe."
            )

    extra: dict = {
        "ema_short": ema_short_last,
        "ema_long": ema_long_last,
        "rsi": rsi_last,
        "rsi_prev": rsi_prev,
        "atr_pct": atr_pct,
    }
    if htf_trend is not None:
        extra["htf_trend"] = htf_trend

    return TradeSignal(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        price=last.close,
        generated_at=datetime.utcnow(),
        reason=reason,
        extra=extra,
    )

