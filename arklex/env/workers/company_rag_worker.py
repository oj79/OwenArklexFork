import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, START
from langchain_community.vectorstores.faiss import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

from arklex.env.workers.faiss_rag_worker import FaissRAGWorker
from arklex.env.workers.worker import register_worker
from arklex.env.tools.utils import ToolGenerator
from arklex.env.tools.RAG.retrievers.faiss_retriever import RetrieveEngine
from arklex.utils.graph_state import MessageState
from arklex.utils.loader import Loader, DocObject

logger = logging.getLogger(__name__)


@register_worker
class CompanyRAGWorker(FaissRAGWorker):
    """RAG worker that ingests company filings asynchronously."""

    description: str = (
        "Answer the user's questions based on parsed filings and documents"
    )

    def __init__(
        self,
        doc_paths: Optional[List[str]] = None,
        data_dir: str = os.environ.get("DATA_DIR", "./company_rag"),
        stream_response: bool = True,
        use_milvus: bool = False,
    ) -> None:
        self.doc_paths = doc_paths or []
        self.data_dir = data_dir
        self.use_milvus = use_milvus
        self.embedding_model = OpenAIEmbeddings()
        self.index_path = os.path.join(self.data_dir, "index")
        self.docs_file = os.path.join(self.data_dir, "processed.json")
        self.index: Optional[FAISS] = None
        self.loader = Loader()
        os.makedirs(self.data_dir, exist_ok=True)
        self._schedule_index_init()
        super().__init__(stream_response=stream_response)

    # Initialization helpers -------------------------------------------------

    def _schedule_index_init(self) -> None:
        """Load existing index and ingest documents asynchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(self._ensure_index())
        else:
            asyncio.run(self._ensure_index())

    async def _ensure_index(self) -> None:
        await self._load_index()
        await self._check_for_updates()

    async def _load_index(self) -> None:
        if self.use_milvus:
            return
        if os.path.isdir(self.index_path):
            try:
                self.index = FAISS.load_local(self.index_path, self.embedding_model)
            except Exception as err:
                logger.error(f"Failed to load index: {err}")
                self.index = None
        else:
            self.index = None

    async def _save_index(self) -> None:
        if self.index is not None and not self.use_milvus:
            self.index.save_local(self.index_path)

    def _load_processed(self) -> Dict[str, float]:
        if os.path.exists(self.docs_file):
            with open(self.docs_file, "r") as f:
                return json.load(f)
        return {}

    def _save_processed(self, data: Dict[str, float]) -> None:
        with open(self.docs_file, "w") as f:
            json.dump(data, f)

    # Ingestion --------------------------------------------------------------

    async def _ingest_file(self, file_path: str) -> None:
        doc_obj = DocObject(str(uuid.uuid4()), file_path)
        crawled = await asyncio.to_thread(self.loader.crawl_file, doc_obj)
        if crawled.content is None:
            return
        docs: List[Document] = Loader.chunk([crawled])

        if self.use_milvus:
            # Import here so that environments without Milvus installed do not
            # fail at module import time.
            try:
                from arklex.env.tools.RAG.retrievers.milvus_retriever import (
                    MilvusRetriever,
                )

                retriever = MilvusRetriever()
                try:
                    docs_to_insert = [
                        {
                            "id": d.id,
                            "qa_doc_id": d.id,
                            "chunk_idx": 0,
                            "qa_doc_type": 0,
                            "text": d.page_content,
                            "metadata": d.metadata,
                            "is_chunked": True,
                            "bot_uid": "company_rag",
                            "timestamp": int(os.path.getmtime(file_path)),
                        }
                        for d in docs
                    ]
                    retriever.add_documents_dicts(
                        documents=docs_to_insert,
                        collection_name="company_rag",
                        upsert=True,
                    )
                finally:
                    retriever.__exit__(None, None, None)
            except Exception as err:
                logger.error(
                    "Milvus ingestion failed; falling back to local FAISS. Error: %s",
                    err,
                )
                if self.index is None:
                    self.index = FAISS.from_documents(docs, self.embedding_model)
                else:
                    self.index.add_documents(docs)
        else:
            if self.index is None:
                self.index = FAISS.from_documents(docs, self.embedding_model)
            else:
                self.index.add_documents(docs)

    async def _ingest_paths(self, paths: List[str]) -> None:
        tasks = [asyncio.create_task(self._ingest_file(p)) for p in paths]
        if tasks:
            await asyncio.gather(*tasks)
            await self._save_index()

    async def _check_for_updates(self) -> None:
        processed = self._load_processed()
        new_files: List[str] = []
        for src in self.doc_paths:
            if os.path.isdir(src):
                for root, _, files in os.walk(src):
                    for fn in files:
                        if not fn.lower().endswith(("pdf", "html", "htm")):
                            continue
                        p = os.path.join(root, fn)
                        mtime = os.path.getmtime(p)
                        if processed.get(p) != mtime:
                            processed[p] = mtime
                            new_files.append(p)
            elif os.path.isfile(src):
                if src.lower().endswith(("pdf", "html", "htm")):
                    mtime = os.path.getmtime(src)
                    if processed.get(src) != mtime:
                        processed[src] = mtime
                        new_files.append(src)

        if new_files:
            logger.info("Ingesting %d new documents", len(new_files))
            await self._ingest_paths(new_files)
            self._save_processed(processed)

    # Workflow ----------------------------------------------------------------

    def _create_action_graph(self) -> StateGraph:
        workflow = StateGraph(MessageState)
        if self.use_milvus:
            from arklex.env.tools.RAG.retrievers.milvus_retriever import (
                RetrieveEngine as MilvusRE,
            )
            workflow.add_node("retriever", MilvusRE.milvus_retrieve)
        else:
            workflow.add_node("retriever", RetrieveEngine.faiss_retrieve)
        workflow.add_node("tool_generator", ToolGenerator.context_generate)
        workflow.add_node("stream_tool_generator", ToolGenerator.stream_context_generate)
        workflow.add_edge(START, "retriever")
        workflow.add_conditional_edges("retriever", self.choose_tool_generator)
        return workflow

    # Execution ---------------------------------------------------------------

    def _execute(self, msg_state: MessageState, **kwargs: Any) -> Dict[str, Any]:
        asyncio.run(self._check_for_updates())
        self.action_graph = self._create_action_graph()
        graph = self.action_graph.compile()
        result: Dict[str, Any] = graph.invoke(msg_state)
        return result