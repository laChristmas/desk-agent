from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    citations: list[dict]  # {doc_id, title, chunk_id, quote}
    last_route: str  # retrieve | query_db | write | respond
    pending_write: dict | None  # interrupt 时的拟写入内容
