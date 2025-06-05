from arklex.env.tools.portfolio.build_portfolio_db import build_portfolio_db
from arklex.env.workers.portfolio_worker import PortfolioWorker
from arklex.utils.graph_state import MessageState, ConvoMessage, BotConfig, LLMConfig
from arklex.utils.model_config import MODEL
import os
from dotenv import load_dotenv

load_dotenv()

class DummySlot:
    def __init__(self, name, value):
        self.name = name
        self.verified_value = value


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
        slots=[
            DummySlot("symbol", "AAPL"),
            DummySlot("quantity", 10),
            DummySlot("price", 150),
            DummySlot("side", "buy"),
        ],
    )

    worker.PFActions.add_trade(msg_state)

    view_state = MessageState(bot_config=bot_cfg)
    result = worker.PFActions.get_portfolio(view_state)
    assert "AAPL" in result.message_flow