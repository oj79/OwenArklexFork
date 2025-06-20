import logging
from typing import Dict

from langgraph.graph import StateGraph, START
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.language_models import BaseChatModel

from arklex.env.workers.worker import BaseWorker, register_worker
from arklex.env.prompts import load_prompts
from arklex.env.tools.utils import ToolGenerator
from arklex.env.tools.portfolio.utils import PortfolioActions
from arklex.utils.utils import chunk_string
from arklex.utils.graph_state import MessageState
from arklex.utils.model_config import MODEL

logger = logging.getLogger(__name__)


@register_worker
class PortfolioWorker(BaseWorker):
    """Worker to manage portfolio trades, positions and notes."""

    description: str = (
        "Record trades, show portfolio positions and manage investment notes."
    )

    def __init__(self) -> None:
        self.llm: BaseChatModel = ChatOpenAI(model=MODEL["model_type_or_path"], timeout=30000)
        self.actions: Dict[str, str] = {
            "AddTrade": "Record a trade transaction",
            "ViewPortfolio": "Show current portfolio positions",
            "AddNote": "Store a portfolio note",
            "ViewNotes": "Show recent notes",
            "Others": "Other actions",
        }
        self.PFActions: PortfolioActions = PortfolioActions()
        self.action_graph: StateGraph = self._create_action_graph()

    def add_trade(self, state: MessageState) -> MessageState:
        return self.PFActions.add_trade(state)

    def view_portfolio(self, state: MessageState) -> MessageState:
        return self.PFActions.get_portfolio(state)

    def add_note(self, state: MessageState) -> MessageState:
        return self.PFActions.add_note(state)

    def view_notes(self, state: MessageState) -> MessageState:
        return self.PFActions.view_notes(state)

    def verify_action(self, msg_state: MessageState) -> str:
        user_intent = msg_state.orchestrator_message.attribute.get("task", "")
        actions_info = "\n".join([f"{name}: {desc}" for name, desc in self.actions.items()])
        actions_name = ", ".join(self.actions.keys())
        prompts = load_prompts(msg_state.bot_config)
        prompt = PromptTemplate.from_template(prompts["database_action_prompt"])
        input_prompt = prompt.invoke({"user_intent": user_intent, "actions_info": actions_info, "actions_name": actions_name})
        chunked_prompt = chunk_string(input_prompt.text, tokenizer=MODEL["tokenizer"], max_length=MODEL["context"])
        logger.info(f"Chunked prompt for deciding portfolio action: {chunked_prompt}")
        final_chain = self.llm | StrOutputParser()
        try:
            answer = final_chain.invoke(chunked_prompt)
            for action_name in self.actions.keys():
                if action_name in answer:
                    logger.info(f"Chosen portfolio action: {action_name}")
                    return action_name
            logger.info("Base action chosen in the portfolio worker: Others")
            return "Others"
        except Exception as e:
            logger.error(f"Error choosing action in portfolio worker: {e}")
            return "Others"

    def _create_action_graph(self) -> StateGraph:
        workflow = StateGraph(MessageState)
        workflow.add_node("AddTrade", self.add_trade)
        workflow.add_node("ViewPortfolio", self.view_portfolio)
        workflow.add_node("AddNote", self.add_note)
        workflow.add_node("ViewNotes", self.view_notes)
        workflow.add_node("Others", ToolGenerator.generate)
        workflow.add_node("tool_generator", ToolGenerator.context_generate)
        workflow.add_conditional_edges(START, self.verify_action)
        workflow.add_edge("AddTrade", "tool_generator")
        workflow.add_edge("ViewPortfolio", "tool_generator")
        workflow.add_edge("AddNote", "tool_generator")
        workflow.add_edge("ViewNotes", "tool_generator")
        return workflow


    def _execute(self, msg_state: MessageState, **kwargs) -> MessageState:
        if hasattr(self.PFActions, "init_slots"):
            msg_state.slots = self.PFActions.init_slots(msg_state.slots, msg_state.bot_config)
        graph = self.action_graph.compile()
        result: MessageState = graph.invoke(msg_state)
        return result