import asyncio
import time
import json
from typing import Any, Dict, Tuple

import yfinance as yf

from arklex.env.tools.tools import register_tool

CACHE_TTL = 300  # seconds
_cache: Dict[Tuple[str, str, str], Tuple[float, Any]] = {}


async def _fetch_yahoo(symbol: str, period: str, interval: str) -> Any:
    cache_key = (symbol, period, interval)
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < CACHE_TTL:
        return _cache[cache_key][1]
    df = await asyncio.to_thread(
        yf.download, tickers=symbol, period=period, interval=interval
    )
    df = df.reset_index()
    df.columns = [
        "_".join(map(str, col)) if isinstance(col, tuple) else str(col)
        for col in df.columns
    ]
    result = df.to_dict(orient="records")
    _cache[cache_key] = (time.time(), result)
    return result


description = "Fetch historical stock prices from Yahoo Finance"
slots = [
    {"name": "symbol", "type": "str", "description": "Ticker symbol, e.g. AAPL", "required": True},
    {"name": "period", "type": "str", "description": "Data period like 5d or 1mo", "required": False},
    {"name": "interval", "type": "str", "description": "Data interval like 1d or 1wk", "required": False},
]


@register_tool(description, slots)
def get_yahoo_history(symbol: str, period: str = "5d", interval: str = "1d") -> str:
    data = asyncio.run(_fetch_yahoo(symbol, period, interval))
    return json.dumps(data, default=str)