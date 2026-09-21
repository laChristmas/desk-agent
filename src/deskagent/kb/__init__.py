"""知识库：切块入库与检索。本阶段不经 LLM、不包装成 Agent 工具。"""

from deskagent.kb.ingest import ingest_kb
from deskagent.kb.retrieve import retrieve

__all__ = ["ingest_kb", "retrieve"]
