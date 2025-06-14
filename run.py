import argparse
import json
import logging
import os
import time
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from pprint import pprint

from arklex.env.env import Env
from arklex.orchestrator.orchestrator import AgentOrg
from arklex.utils.model_config import MODEL
from arklex.utils.model_provider_config import LLM_PROVIDERS
from arklex.utils.utils import init_logger

load_dotenv()


def pprint_with_color(
    data: Any, color_code: str = "\033[34m"
) -> None:  # Default to blue
    print(color_code, end="")  # Set the color
    pprint(data)
    print("\033[0m", end="")


def get_api_bot_response(
    config: Dict[str, Any],
    history: List[Dict[str, str]],
    user_text: str,
    parameters: Dict[str, Any],
    env: Env,
) -> Tuple[str, Dict[str, Any], bool]:
    data: Dict[str, Any] = {
        "text": user_text,
        "chat_history": history,
        "parameters": parameters,
    }
    orchestrator = AgentOrg(config=config, env=env)
    result: Dict[str, Any] = orchestrator.get_response(data)

    return result["answer"], result["parameters"], result["human_in_the_loop"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=str, default="./examples/test")
    parser.add_argument("--model", type=str, default=MODEL["model_type_or_path"])
    parser.add_argument(
        "--llm-provider", type=str, default=MODEL["llm_provider"], choices=LLM_PROVIDERS
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    args = parser.parse_args()
    os.environ["DATA_DIR"] = args.input_dir
    model: Dict[str, str] = {
        "model_type_or_path": args.model,
        "llm_provider": args.llm_provider,
    }
    log_level = getattr(logging, args.log_level.upper(), logging.WARNING)
    logger = init_logger(
        log_level=log_level,
        filename=os.path.join(os.path.dirname(__file__), "logs", "arklex.log"),
    )

    # Initialize env
    config: Dict[str, Any] = json.load(
        open(os.path.join(args.input_dir, "taskgraph.json"))
    )
    config["model"] = model
    env = Env(
        tools=config.get("tools", []),
        workers=config.get("workers", []),
        slotsfillapi=config["slotfillapi"],
        planner_enabled=True,
    )

    history: List[Dict[str, str]] = []
    params: Dict[str, Any] = {}
    user_prefix: str = "user"
    worker_prefix: str = "assistant"
    for node in config["nodes"]:
        if node[1].get("type", "") == "start":
            start_message: str = node[1]["attribute"]["value"]
            break
    history.append({"role": worker_prefix, "content": start_message})
    pprint_with_color(f"Bot: {start_message}")

    while True:
        user_text: str = input("You: ")
        if user_text.lower() == "quit":
            break
        start_time: float = time.time()
        output, params, hitl = get_api_bot_response(
            config, history, user_text, params, env
        )
        history.append({"role": user_prefix, "content": user_text})
        history.append({"role": worker_prefix, "content": output})
        print(f"getAPIBotResponse Time: {time.time() - start_time}")
        pprint_with_color(f"Bot: {output}")
