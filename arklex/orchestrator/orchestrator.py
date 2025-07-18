import asyncio
import copy
import janus
import json
import logging
import time
from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda
from typing import Any, Dict, Tuple, List, Optional, Union
from arklex.env.nested_graph.nested_graph import NESTED_GRAPH_ID, NestedGraph
from arklex.env.env import Env
from arklex.orchestrator.task_graph import TaskGraph
from arklex.env.tools.utils import ToolGenerator
from arklex.types import StreamType
from arklex.utils.graph_state import (
    ConvoMessage,
    NodeInfo,
    OrchestratorMessage,
    MessageState,
    PathNode,
    StatusEnum,
    LLMConfig,
    BotConfig,
    Params,
    ResourceRecord,
    OrchestratorResp,
    NodeTypeEnum,
)
from arklex.utils.utils import format_chat_history
from arklex.utils.model_config import MODEL
from arklex.memory import ShortTermMemory
from arklex.env.workers.story_memory_worker import StoryMemoryWorker

load_dotenv()
logger = logging.getLogger(__name__)

INFO_WORKERS: List[str] = [
    "planner",
    "MessageWorker",
    "RagMsgWorker",
    "HITLWorkerChatFlag",
]


class AgentOrg:
    def __init__(
        self, config: Union[str, Dict[str, Any]], env: Env, **kwargs: Any
    ) -> None:
        self.user_prefix: str = "user"
        self.worker_prefix: str = "assistant"
        self.environment_prefix: str = "tool"
        self.__eos_token: str = "\n"
        if isinstance(config, dict):
            self.product_kwargs: Dict[str, Any] = config
        else:
            self.product_kwargs: Dict[str, Any] = json.load(open(config))
        self.llm_config: LLMConfig = LLMConfig(
            **self.product_kwargs.get("model", MODEL)
        )
        self.task_graph: TaskGraph = TaskGraph(
            "taskgraph", self.product_kwargs, self.llm_config
        )
        self.env: Env = env

        # Update planner model info now that LLMConfig is defined
        self.env.planner.set_llm_config_and_build_resource_library(self.llm_config)

        self.story_memory_worker: Optional[StoryMemoryWorker] = None
        for spec in self.env.workers.values():
            if spec["name"] == "StoryMemoryWorker":
                self.story_memory_worker = spec["execute"]()
                break

    def init_params(
        self, inputs: Dict[str, Any]
    ) -> Tuple[str, str, Params, MessageState]:
        text: str = inputs["text"]
        chat_history: List[Dict[str, str]] = inputs["chat_history"]
        input_params: Optional[Dict[str, Any]] = inputs["parameters"]

        # Create base params with defaults
        params: Params = Params()

        # Update with any provided values
        if input_params:
            params = Params.model_validate(input_params)

        # Update specific fields
        chat_history_copy: List[Dict[str, str]] = copy.deepcopy(chat_history)
        chat_history_copy.append({"role": self.user_prefix, "content": text})
        chat_history_str: str = format_chat_history(chat_history_copy)
        # Update turn_id and function_calling_trajectory
        params.metadata.turn_id += 1
        if not params.memory.function_calling_trajectory:
            params.memory.function_calling_trajectory = copy.deepcopy(chat_history_copy)
        else:
            params.memory.function_calling_trajectory.extend(chat_history_copy[-2:])

        params.memory.trajectory.append([])

        # Initialize the message state
        sys_instruct: str = (
            "You are a "
            + self.product_kwargs["role"]
            + ". "
            + self.product_kwargs["user_objective"]
            + self.product_kwargs["builder_objective"]
            + self.product_kwargs["intro"]
            + self.product_kwargs.get("opt_instruct", "")
        )
        bot_config: BotConfig = BotConfig(
            bot_id=self.product_kwargs.get("bot_id", "default"),
            version=self.product_kwargs.get("version", "default"),
            language=self.product_kwargs.get("language", "EN"),
            bot_type=self.product_kwargs.get("bot_type", "presalebot"),
            llm_config=self.llm_config,
        )
        message_state: MessageState = MessageState(
            sys_instruct=sys_instruct,
            bot_config=bot_config,
        )
        return text, chat_history_str, params, message_state

    def check_skip_node(self, node_info: NodeInfo, params: Params) -> bool:
        # NOTE: Do not check the node limit to decide whether the node can be skipped because skipping a node when should not is unwanted.
        return False
        if not node_info.can_skipped:
            return False
        cur_node_id: str = params.taskgraph.curr_node
        if cur_node_id in params.taskgraph.node_limit:
            if params.taskgraph.node_limit[cur_node_id] <= 0:
                return True
        return False

    def post_process_node(
        self, node_info: NodeInfo, params: Params, update_info: Dict[str, Any] = {}
    ) -> Params:
        """
        update_info is a dict of
            skipped = Optional[bool]
        """
        curr_node: str = params.taskgraph.curr_node
        node: PathNode = PathNode(
            node_id=curr_node,
            is_skipped=update_info.get("is_skipped", False),
            in_flow_stack=node_info.add_flow_stack,
            nested_graph_node_value=None,
            nested_graph_leaf_jump=None,
            global_intent=params.taskgraph.curr_global_intent,
        )

        params.taskgraph.path.append(node)

        if curr_node in params.taskgraph.node_limit:
            params.taskgraph.node_limit[curr_node] -= 1
        return params

    def handl_direct_node(
        self, node_info: NodeInfo, params: Params
    ) -> Tuple[bool, Optional[OrchestratorResp], Params]:
        node_attribute: Dict[str, Any] = node_info.attributes
        if node_attribute.get("direct"):
            # Direct response
            if node_attribute.get("value", "").strip():
                params = self.post_process_node(node_info, params)
                return_response: OrchestratorResp = OrchestratorResp(
                    answer=node_attribute["value"], parameters=params.model_dump()
                )
                # Multiple choice list
                if (
                    node_info.type == NodeTypeEnum.MULTIPLE_CHOICE.value
                    and node_attribute.get("choice_list", [])
                ):
                    return_response.choice_list = node_attribute["choice_list"]
                return True, return_response, params
        return False, None, params

    def perform_node(
        self,
        message_state: MessageState,
        node_info: NodeInfo,
        params: Params,
        text: str,
        chat_history_str: str,
        stream_type: Optional[StreamType],
        message_queue: Optional[janus.SyncQueue],
    ) -> Tuple[NodeInfo, MessageState, Params]:
        # Tool/Worker
        node_info, params = self.handle_nested_graph_node(node_info, params)

        user_message: ConvoMessage = ConvoMessage(
            history=chat_history_str, message=text
        )
        orchestrator_message: OrchestratorMessage = OrchestratorMessage(
            message=node_info.attributes["value"], attribute=node_info.attributes
        )

        # Create initial resource record with common info and output from trajectory
        resource_record: ResourceRecord = ResourceRecord(
            info={
                "id": node_info.resource_id,
                "name": node_info.resource_name,
                "attribute": node_info.attributes,
                "node_id": params.taskgraph.curr_node,
            },
            intent=params.taskgraph.intent,
        )

        # Add resource record to current turn's list
        params.memory.trajectory[-1].append(resource_record)

        # Update message state
        message_state.user_message = user_message
        message_state.orchestrator_message = orchestrator_message
        message_state.function_calling_trajectory = (
            params.memory.function_calling_trajectory
        )
        message_state.trajectory = params.memory.trajectory
        message_state.slots = params.taskgraph.dialog_states
        message_state.metadata = params.metadata
        message_state.is_stream = True if stream_type is not None else False
        message_state.message_queue = message_queue

        response_state: MessageState
        response_state, params = self.env.step(
            node_info.resource_id, message_state, params, node_info
        )
        params.memory.trajectory = response_state.trajectory
        return node_info, response_state, params

    def handle_nested_graph_node(
        self, node_info: NodeInfo, params: Params
    ) -> Tuple[NodeInfo, Params]:
        if node_info.resource_id != NESTED_GRAPH_ID:
            return node_info, params
        # if current node is a nested graph resource, change current node to the start of the nested graph
        nested_graph: NestedGraph = NestedGraph(node_info=node_info)
        next_node_id: str = nested_graph.get_nested_graph_start_node_id()
        nested_graph_node: str = params.taskgraph.curr_node
        node: PathNode = PathNode(
            node_id=nested_graph_node,
            is_skipped=False,
            in_flow_stack=False,
            nested_graph_node_value=node_info.attributes["value"],
            nested_graph_leaf_jump=None,
            global_intent=params.taskgraph.curr_global_intent,
        )
        # add nested graph resource node to path
        # start node of the nested graph will be added to the path after performed
        params.taskgraph.path.append(node)
        params.taskgraph.curr_node = next_node_id
        # use incomplete status at the beginning, status will be changed when whole nested graph is traversed
        params.taskgraph.node_status[node_info.node_id] = StatusEnum.INCOMPLETE
        node_info, params = self.task_graph._get_node(next_node_id, params)

        return node_info, params

    def _get_response(
        self,
        inputs: Dict[str, Any],
        stream_type: Optional[StreamType] = None,
        message_queue: Optional[janus.SyncQueue] = None,
    ) -> OrchestratorResp:
        text: str
        chat_history_str: str
        params: Params
        message_state: MessageState
        text, chat_history_str, params, message_state = self.init_params(inputs)
        ##### TaskGraph Chain
        taskgraph_inputs: Dict[str, Any] = {
            "text": text,
            "chat_history_str": chat_history_str,
            "parameters": params,
            "allow_global_intent_switch": True,
        }

        stm = ShortTermMemory(
            params.memory.trajectory, chat_history_str, llm_config=self.llm_config
        )
        asyncio.run(stm.personalize())
        message_state.trajectory = params.memory.trajectory

        # Log personalized intents from trajectory
        for turn in params.memory.trajectory:
            for record in turn:
                if record.personalized_intent:
                    logger.info(f"Personalized Intent: {record.personalized_intent}")
                    logger.info(f"Original Intent: {record.personalized_intent}")

        found_records, relevant_records = stm.retrieve_records(text)

        if self.story_memory_worker:
            story_records = self.story_memory_worker.retrieve_stories(text)
            if story_records:
                found_records = True
                relevant_records.extend(story_records)

        logger.info(f"Found Records: {found_records}")
        if found_records:
            logger.info(
                f"Relevant Records: {[r.personalized_intent for r in relevant_records]}"
            )

        found_intent, relevant_intent = stm.retrieve_intent(text)

        logger.info(f"Found Intent: {found_intent}")
        if found_intent:
            logger.info(f"Relevant Intent: {relevant_intent}")

        if found_records:
            message_state.relevant_records = relevant_records
        taskgraph_chain = RunnableLambda(self.task_graph.get_node) | RunnableLambda(
            self.task_graph.postprocess_node
        )

        # TODO: when planner is re-implemented, execute/break the loop based on whether the planner should be used (bot config).
        msg_counter = 0

        n_node_performed = 0
        max_n_node_performed = 5
        while n_node_performed < max_n_node_performed:
            taskgraph_start_time = time.time()
            if found_intent:
                taskgraph_inputs["allow_global_intent_switch"] = False
                node_info = NodeInfo(
                    node_id=None,
                    type="",
                    resource_id="planner",
                    resource_name="planner",
                    can_skipped=False,
                    is_leaf=len(
                        list(
                            self.task_graph.graph.successors(params.taskgraph.curr_node)
                        )
                    )
                    == 0,
                    attributes={"value": "", "direct": False},
                )
            else:
                node_info, params = taskgraph_chain.invoke(taskgraph_inputs)
            taskgraph_inputs["allow_global_intent_switch"] = False
            params.metadata.timing.taskgraph = time.time() - taskgraph_start_time
            # Check if current node can be skipped
            can_skip = self.check_skip_node(node_info, params)
            if can_skip:
                params = self.post_process_node(node_info, params, {"is_skipped": True})
                continue
            logger.info(f"The current node info is : {node_info}")

            # handle direct node
            is_direct_node, direct_response, params = self.handl_direct_node(
                node_info, params
            )
            if is_direct_node:
                return direct_response
            # perform node

            node_info, message_state, params = self.perform_node(
                message_state,
                node_info,
                params,
                text,
                chat_history_str,
                stream_type,
                message_queue,
            )
            params = self.post_process_node(node_info, params)

            n_node_performed += 1
            # If the current node is not complete, then no need to continue to the next node
            node_status = params.taskgraph.node_status
            cur_node_id = params.taskgraph.curr_node
            status = node_status.get(cur_node_id, StatusEnum.COMPLETE)
            if status == StatusEnum.INCOMPLETE:
                break

            # Check current node attributes
            if node_info.resource_name in INFO_WORKERS:
                msg_counter += 1
            # If the counter of message worker or counter of planner or counter of ragmsg worker == 1, break the loop
            if msg_counter == 1:
                break
            if node_info.is_leaf is True:
                break

        if not message_state.response:
            logger.info("No response, do context generation")
            if not stream_type:
                message_state = ToolGenerator.context_generate(message_state)
            else:
                message_state = ToolGenerator.stream_context_generate(message_state)

        if self.story_memory_worker:
            try:
                self.story_memory_worker.add_story(message_state)
            except Exception as err:
                logger.error(f"StoryMemoryWorker add_story failed: {err}")

        return OrchestratorResp(
            answer=message_state.response,
            parameters=params.model_dump(),
            human_in_the_loop=params.metadata.hitl,
        )

    def get_response(
        self,
        inputs: Dict[str, Any],
        stream_type: Optional[StreamType] = None,
        message_queue: Optional[janus.SyncQueue] = None,
    ) -> Dict[str, Any]:
        orchestrator_response = self._get_response(inputs, stream_type, message_queue)
        return orchestrator_response.model_dump()
