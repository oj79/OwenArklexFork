import os
import asyncio
import time
from typing import Any, Dict, Tuple

import httpx
import json

from arklex.env.tools.tools import register_tool
from arklex.exceptions import AuthenticationError


CACHE_TTL = 300  # seconds
RATE_LIMIT = 5   # requests per minute for free tier

_cache: Dict[Tuple[str, str, str], Tuple[float, Any]] = {}
_request_times = []  # timestamps of recent requests


async def _rate_limited_request(url: str, params: Dict[str, str]) -> Any:
    """Send an HTTP request respecting Alpha Vantage rate limits."""
    # purge timestamps older than 60 seconds
    now = time.time()
    global _request_times
    _request_times = [t for t in _request_times if now - t < 60]
    if len(_request_times) >= RATE_LIMIT:
        sleep_for = 60 - (now - _request_times[0])
        await asyncio.sleep(max(sleep_for, 0))
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        _request_times.append(time.time())
        return resp.json()


async def _fetch_alpha_vantage(symbol: str, function: str, outputsize: str) -> Any:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise AuthenticationError("Missing ALPHA_VANTAGE_API_KEY")
    cache_key = (symbol, function, outputsize)
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < CACHE_TTL:
        return _cache[cache_key][1]
    params = {
        "function": function,
        "symbol": symbol,
        "outputsize": outputsize,
        "apikey": api_key,
    }
    data = await _rate_limited_request("https://www.alphavantage.co/query", params)
    _cache[cache_key] = (time.time(), data)
    return data


description = "Fetch daily time series data from Alpha Vantage"
slots = [
    {"name": "symbol", "type": "str", "description": "Ticker symbol, e.g. AAPL", "required": True},
]


@register_tool(description, slots)
def get_alpha_daily(symbol: str, function: str = "TIME_SERIES_DAILY_ADJUSTED", outputsize: str = "compact") -> str:
    """Return JSON string with daily time series data."""
    data = asyncio.run(_fetch_alpha_vantage(symbol, function, outputsize))
    return json.dumps(data)