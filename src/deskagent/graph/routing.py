"""路由节点：把用户问题分到 retrieve / query_db / write / respond。

检索、查库、写入的副作用不同，写入必须先中断，因此不用单次 ReAct 包一层。

规则：
1. 问政策 / 怎么规定 / 出处 → retrieve，禁止只靠模型记忆。
2. 问任务 / 谁负责 / 状态 → query_db。
3. 创建 / 更新 / 删除 / 关闭 /「帮我建一条」→ write。
4. 寒暄、或总结已经检索到的内容 → respond。
5. 刚检索完且 citations 为空时，不要再 retrieve；选 respond，由回复节点拒答。
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from deskagent.config import get_settings
from deskagent.graph.state import AgentState

RouteName = Literal["retrieve", "query_db", "write", "respond"]

ROUTER_SYSTEM = """你是 Northwind Labs 内部工作台的路由分类器，只负责选择下一步，不回答用户。
只能输出四个 route 之一：

- retrieve：制度、政策、流程、数字、出处、文档里怎么规定。即使你觉得自己记得，也必须 retrieve。
- query_db：查任务列表、某条任务、负责人、状态。不要去搜文档。
- write：创建待办、改状态、删除任务、关闭任务。用户说「按刚才的结论建一条」也算 write。
- respond：打招呼、闲聊、或根据已经检索/查库的结果做总结。不要在这里编造未检索的制度。

若对话里已经检索过且没有可用出处，而用户仍在问制度，选 respond（拒答），不要再次 retrieve。
若用户已经拿到检索结论，接着要求建待办，选 write。
"""


class RouteDecision(BaseModel):
    route: RouteName = Field(description="下一步节点")


def get_chat_model() -> ChatOpenAI:
    """OpenAI 兼容接口（通义等）。节点里也可以复用。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key or "EMPTY",
        base_url=settings.llm_base_url,
        temperature=0,
    )


def route(state: AgentState) -> dict:
    """根据 messages 做结构化路由，写入 last_route。不调工具、不写库。"""
    llm = get_chat_model().with_structured_output(RouteDecision)
    decision = llm.invoke(
        [SystemMessage(content=ROUTER_SYSTEM), *state.get("messages", [])]
    )
    return {"last_route": decision.route}
