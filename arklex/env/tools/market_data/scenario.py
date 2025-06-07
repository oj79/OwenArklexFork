import json
from arklex.env.tools.tools import register_tool

description = "Apply a percentage change to a value"
slots = [
    {"name": "value", "type": "float", "description": "Base value", "required": True},
    {
        "name": "pct_change",
        "type": "float",
        "description": "Percentage change e.g. -0.05 for -5%",
        "required": True,
    },
]


@register_tool(description, slots)
def apply_pct_change(value: float, pct_change: float) -> str:
    new_value = value * (1 + pct_change)
    return json.dumps({"new_value": new_value})