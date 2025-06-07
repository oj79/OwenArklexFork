import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import httpx
from langgraph.graph import StateGraph, START

from arklex.env.workers.worker import BaseWorker, register_worker
from arklex.utils.graph_state import MessageState
from arklex.env.tools.utils import ToolGenerator

logger = logging.getLogger(__name__)


@register_worker
class NewsEventWorker(BaseWorker):
    """Worker that polls news RSS feeds and summarizes articles."""

    description: str = (
        "Monitor news feeds and provide recent articles as context for analysis"
    )

    def __init__(self, feeds: Optional[List[str]] = None) -> None:
        super().__init__()
        self.feeds = feeds or []
        self.action_graph: StateGraph = self._create_action_graph()

    async def _fetch_feed(self, url: str) -> List[str]:
        """Fetch up to 3 article titles from an RSS/Atom feed."""
        try:
            if os.path.exists(url):
                data = open(url, "r").read()
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.text
            root = ET.fromstring(data)
            items = []
            for item in root.findall(".//item")[:3]:
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                if title:
                    items.append(f"{title} ({link})")
            if not items:
                for entry in root.findall(".//entry")[:3]:
                    title = entry.findtext("title", "").strip()
                    link = entry.findtext("link", "")
                    if link and isinstance(link, str):
                        href = link
                    elif hasattr(link, 'attrib'):
                        href = link.attrib.get('href', '')
                    else:
                        href = ""
                    if title:
                        items.append(f"{title} ({href})")
            return items
        except Exception as err:
            logger.error("Failed to fetch %s: %s", url, err)
            return []

    async def _gather_news(self) -> str:
        articles: List[str] = []
        for feed in self.feeds:
            articles.extend(await self._fetch_feed(feed))
        return "\n".join(articles)

    # ------------------------------------------------------------------
    def fetch_news(self, state: MessageState) -> MessageState:
        news = asyncio.run(self._gather_news())
        state.message_flow = news
        return state

    def _create_action_graph(self) -> StateGraph:
        workflow = StateGraph(MessageState)
        workflow.add_node("fetch_news", self.fetch_news)
        workflow.add_node("tool_generator", ToolGenerator.context_generate)
        workflow.add_edge(START, "fetch_news")
        workflow.add_edge("fetch_news", "tool_generator")
        return workflow

    def _execute(self, msg_state: MessageState, **kwargs: Any) -> Dict[str, Any]:
        graph = self.action_graph.compile()
        result: Dict[str, Any] = graph.invoke(msg_state)
        return result