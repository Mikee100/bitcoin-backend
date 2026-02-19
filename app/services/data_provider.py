from __future__ import annotations

from datetime import datetime
from typing import List

import httpx

from app.config import get_settings
from app.models import Candle, Timeframe


BINANCE_BASE_URL = "https://api.binance.com"


async def fetch_klines(
    symbol: str,
    timeframe: Timeframe,
    limit: int = 200,
) -> List[Candle]:
    """
    Fetch recent OHLCV candles for a symbol and timeframe from Binance.

    This uses the public klines endpoint (no auth required).
    
    Raises:
        httpx.HTTPError: If the request fails or times out
    """
    settings = get_settings()
    symbol = symbol or settings.default_symbol

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": timeframe.value, "limit": limit}

    # Increased timeout to 30 seconds and added connection timeout
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            raise httpx.HTTPError(
                f"Failed to fetch klines from Binance: {type(e).__name__}. "
                f"Please check your internet connection and try again."
            ) from e

    candles: List[Candle] = []
    for item in raw:
        # See Binance docs for kline array format
        open_time_ms = item[0]
        open_price = float(item[1])
        high_price = float(item[2])
        low_price = float(item[3])
        close_price = float(item[4])
        volume = float(item[5])

        candles.append(
            Candle(
                open_time=datetime.utcfromtimestamp(open_time_ms / 1000.0),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
        )

    return candles

