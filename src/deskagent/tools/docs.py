"""知识检索工具。阶段二只返回 JSON 字符串；LangGraph / @tool 放到阶段三。"""

from __future__ import annotations

import json

from deskagent.kb.retrieve import retrieve


def search_docs(query: str, k: int = 4) -> str:
    """按 query 检索知识库，返回 {"hits": [...]}；无命中则为空列表。"""
    hits = retrieve(query, k)
    return json.dumps({"hits": hits}, ensure_ascii=False)
