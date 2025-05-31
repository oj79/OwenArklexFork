import os
import asyncio
import time
from typing import Any, Dict, Tuple

import httpx
import json

from arklex.env.tools.tools import register_tool
from arklex.exceptions import AuthenticationError

CACHE_TTL = 300  # seconds
RATE_LIMIT = 10  # FRED limits ~100 per minute but we'll be conservative

_cache: Dict[str, Tuple[float, Any]] = {}
_request_times = []


async def _rate_limited_request(url: str, params: Dict[str, str]) -> Any:
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


async def _fetch_fred_series(series_id: str, observation_start: str = "", observation_end: str = "") -> Any:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise AuthenticationError("Missing FRED_API_KEY")
    cache_key = (series_id, observation_start, observation_end)
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < CACHE_TTL:
        return _cache[cache_key][1]
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if observation_start:
        params["observation_start"] = observation_start
    if observation_end:
        params["observation_end"] = observation_end
    data = await _rate_limited_request("https://api.stlouisfed.org/fred/series/observations", params)
    _cache[cache_key] = (time.time(), data)
    return data


description = "Fetch FRED economic time series"
slots = [
    {"name": "series_id", "type": "str", "description": "FRED series ID", "required": True},
]


@register_tool(description, slots)
def get_fred_series(series_id: str, observation_start: str = "", observation_end: str = "") -> str:
    data = asyncio.run(_fetch_fred_series(series_id, observation_start, observation_end))
    return json.dumps(data)