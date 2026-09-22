"""组装 Agent 图：路由后四选一，检索 / 查库 / 写入之后都进 respond。

interrupt 依赖 Checkpointer 与 thread_id。暂停发生在 write 节点返回之前，
拟写入在 interrupt 的 payload 里，要用 get_state(config) 读，不能靠节点 return。
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from deskagent.config import get_settings
from deskagent.graph.nodes import query_db_node, respond_node, retrieve_node, write_node
from deskagent.graph.routing import route
from deskagent.graph.state import AgentState


def _after_router(state: AgentState) -> str:
    return state["last_route"]


def _make_checkpointer() -> SqliteSaver:
    """长期持有 SQLite 连接；from_conn_string 退出 with 后连接会关掉。"""
    path = get_settings().checkpoint_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(conn)


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("router", route)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("query_db", query_db_node)
    builder.add_node("write", write_node)
    builder.add_node("respond", respond_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        _after_router,
        {
            "retrieve": "retrieve",
            "query_db": "query_db",
            "write": "write",
            "respond": "respond",
        },
    )
    builder.add_edge("retrieve", "respond")
    builder.add_edge("query_db", "respond")
    builder.add_edge("write", "respond")
    builder.add_edge("respond", END)
    return builder


@lru_cache(maxsize=1)
def get_graph() -> CompiledStateGraph:
    """进程内只 compile 一次，与 Checkpointer 共用同一条 SQLite 连接。"""
    return build_graph().compile(checkpointer=_make_checkpointer())
