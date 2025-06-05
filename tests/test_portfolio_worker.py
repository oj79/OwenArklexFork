from arklex.env.tools.portfolio.build_portfolio_db import build_portfolio_db
from arklex.env.workers.portfolio_worker import PortfolioWorker
from arklex.utils.graph_state import MessageState, ConvoMessage, BotConfig, LLMConfig
from arklex.utils.slot import Slot
from arklex.utils.model_config import MODEL
import os
from dotenv import load_dotenv

load_dotenv()

def _make_slot(name: str, value):
    """Create a Slot instance with a verified value for testing."""
    slot = Slot(name=name)
    # Slots don't define ``verified_value`` so set it dynamically
    object.__setattr__(slot, "verified_value", value)
    return slot


def test_add_trade_and_view(tmp_path):
    db_dir = tmp_path
    build_portfolio_db(str(db_dir))
    os.environ["DATA_DIR"] = str(db_dir)
    worker = PortfolioWorker()

    llm_config = LLMConfig(**MODEL)
    bot_cfg = BotConfig(
        bot_id="test",
        version="0",
        language="EN",
        bot_type="test",
        llm_config=llm_config,
    )

    msg_state = MessageState(
        user_message=ConvoMessage(history="", message="add"),
        bot_config=bot_cfg,
        slots={
            "AddTrade": [
                _make_slot("symbol", "AAPL"),
                _make_slot("quantity", 10),
                _make_slot("price", 150),
                _make_slot("side", "buy"),
            ]
        },
    )

    add_state = msg_state.model_copy()
    add_state.slots = msg_state.slots["AddTrade"]
    worker.PFActions.add_trade(add_state)

    view_state = MessageState(bot_config=bot_cfg)
    result = worker.PFActions.get_portfolio(view_state)
    assert "AAPL" in result.message_flow