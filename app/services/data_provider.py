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
    Fetch recent OHLCV candles for a symbol and timeframe from Binance public API.

    Docs: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
    Raises:
        httpx.HTTPError: If the request fails or times out
    """
    settings = get_settings()
    use_symbol = (symbol or settings.default_symbol).upper()

    interval_map = {
        "15m": "15m",
        "1h": "1h",
    }
    interval = interval_map.get(timeframe.value, "15m")

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": use_symbol,
        "interval": interval,
        "limit": limit,
    }

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            print(f"[fetch_klines] Connection error: {e}")
            raise httpx.HTTPError(
                f"Failed to fetch klines from Binance: {type(e).__name__}. "
                f"Please check your internet connection and try again."
            ) from e
        except httpx.HTTPStatusError as e:
            print(f"[fetch_klines] HTTP status error: {e.response.status_code} {e.response.text}")
            raise httpx.HTTPError(
                f"Binance API returned status {e.response.status_code}: {e.response.text}"
            ) from e
        except Exception as e:
            print(f"[fetch_klines] Unexpected error: {e}")
            raise httpx.HTTPError(
                f"Unexpected error fetching klines: {str(e)}"
            ) from e

    candles: List[Candle] = []
    # Binance kline format: [open_time, open, high, low, close, volume, close_time, ...]
    for item in raw:
        open_time_ms = int(item[0])
        open_price = float(item[1])
        high_price = float(item[2])
        low_price = float(item[3])
        close_price = float(item[4])
        volume = float(item[5])

        candles.append(
            Candle(
                open_time=datetime.utcfromtimestamp(open_time_ms / 1000),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
        )

    return candles

