import json
from typing import Dict

from arklex.env.tools.tools import register_tool

positive_words = {"good", "great", "bull", "bullish", "up", "positive", "gain"}
negative_words = {"bad", "bear", "bearish", "down", "negative", "loss"}

description = "Perform simple sentiment analysis on text"
slots = [
    {"name": "text", "type": "str", "description": "Input text", "required": True},
]


@register_tool(description, slots)
def simple_sentiment(text: str) -> str:
    """Return a naive sentiment score based on word counts."""
    text_lower = text.lower()
    score = 0
    for w in positive_words:
        if w in text_lower:
            score += 1
    for w in negative_words:
        if w in text_lower:
            score -= 1
    label = "neutral"
    if score > 0:
        label = "positive"
    elif score < 0:
        label = "negative"
    return json.dumps({"sentiment": label, "score": score})