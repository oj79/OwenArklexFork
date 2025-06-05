from arklex.exceptions import ExceptionPrompt


class MarketDataExceptionPrompt(ExceptionPrompt):
    """Exception prompts for market data tools."""

    FRED_REQUEST_ERROR_PROMPT: str = (
        "Could not retrieve data from FRED. Please check the series ID and API key or try again later."
    )