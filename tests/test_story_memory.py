import os
import sqlite3
from arklex.env.tools.story_memory.build_story_memory import build_story_memory
from arklex.env.workers.story_memory_worker import StoryMemoryWorker
from arklex.utils.graph_state import MessageState, ConvoMessage, BotConfig, LLMConfig
from arklex.utils.model_config import MODEL


def test_add_and_retrieve(tmp_path):
    db_dir = tmp_path
    build_story_memory(str(db_dir))
    db_path = os.path.join(db_dir, "stories.sqlite")
    worker = StoryMemoryWorker(db_path=db_path)

    llm_config = LLMConfig(**MODEL)
    bot_cfg = BotConfig(
        bot_id="test",
        version="0",
        language="EN",
        bot_type="test",
        llm_config=llm_config,
    )
    msg_state = MessageState(
        user_message=ConvoMessage(history="", message="hello"),
        bot_config=bot_cfg,
        response="hi",
    )

    worker.add_story(msg_state)
    results = worker.retrieve_stories("hello", top_k=1)
    assert len(results) == 1
    assert "hello" in results[0].output