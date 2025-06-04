import numpy as np
import json
from typing import List

from arklex.env.tools.tools import register_tool


description_var = "Compute Value at Risk (VaR) for a series of returns"
slots_var = [
    {"name": "returns", "type": "list", "description": "List of periodic returns", "required": True},
    {"name": "confidence", "type": "float", "description": "Confidence level e.g. 0.95", "required": False},
]


@register_tool(description_var, slots_var)
def value_at_risk(returns: List[float], confidence: float = 0.95) -> str:
    arr = np.array(returns, dtype=float)
    cutoff = np.percentile(arr, (1 - confidence) * 100)
    return json.dumps({"VaR": float(-cutoff)})

description_draw = "Compute max drawdown from a list of portfolio values"
slots_draw = [
    {"name": "values", "type": "list", "description": "Sequence of portfolio values", "required": True},
]


@register_tool(description_draw, slots_draw)
def max_drawdown(values: List[float]) -> str:
    arr = np.array(values, dtype=float)
    cumulative_max = np.maximum.accumulate(arr)
    drawdowns = (arr - cumulative_max) / cumulative_max
    return json.dumps({"max_drawdown": float(drawdowns.min())})

description_sharpe = "Compute annualized Sharpe ratio from returns"
slots_sharpe = [
    {"name": "returns", "type": "list", "description": "List of periodic returns", "required": True},
    {"name": "risk_free", "type": "float", "description": "Risk-free rate per period", "required": False},
]


@register_tool(description_sharpe, slots_sharpe)
def sharpe_ratio(returns: List[float], risk_free: float = 0.0) -> str:
    arr = np.array(returns, dtype=float)
    excess = arr - risk_free
    sr = np.mean(excess) / (np.std(excess) + 1e-8)
    return json.dumps({"sharpe": float(sr)})