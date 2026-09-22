"""图节点：检索、查库、写入（含中断）、回复。

写入在 interrupt 返回之前不得调用 create_task / update_task_status。
LangGraph 从节点开头重跑 resume，因此拟写入内容每次都会再整理一遍，真正写库仍只发生在确认之后。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel

from deskagent.config import get_settings
from deskagent.db import ALLOWED_STATUS
from deskagent.graph.routing import get_chat_model
from deskagent.graph.state import AgentState
from deskagent.tools.docs import search_docs
from deskagent.tools.tasks import create_task, get_task, list_tasks, update_task_status


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _last_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages") or []):
        kind = getattr(message, "type", None)
        if kind == "human" or isinstance(message, HumanMessage):
            return _message_text(message)
        if isinstance(message, dict) and message.get("role") in {"user", "human"}:
            return _message_text(message)
    return ""


def _parse_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _known_users() -> list[dict]:
    path = get_settings().seed_dir / "users.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _user_catalog_text() -> str:
    users = _known_users()
    if not users:
        return "当前没有可用的用户名册，owner_id 仅在用户明确给出 id 时填写。"
    return "已知用户（把提到的姓名映射为 id，未提及则 owner_id 留空）：\n" + json.dumps(
        users, ensure_ascii=False
    )


def retrieve_node(state: AgentState) -> dict:
    """只调 search_docs，把 citations 写入 state，不生成最终答复。"""
    query = _last_user_text(state)
    raw = search_docs(query)
    payload = _parse_json(raw)
    hits = payload.get("hits") or []
    citations = [
        {
            "doc_id": hit.get("doc_id", ""),
            "title": hit.get("title", ""),
            "chunk_id": hit.get("chunk_id", ""),
            "quote": hit.get("text", ""),
        }
        for hit in hits
        if isinstance(hit, dict)
    ]
    return {
        "messages": [AIMessage(content=f"[search_docs]\n{raw}")],
        "citations": citations,
        "last_route": "retrieve",
    }


class DbQuery(BaseModel):
    action: Literal["list_tasks", "get_task"]
    status: str | None = None
    owner_id: str | None = None
    task_id: str | None = None


def query_db_node(state: AgentState) -> dict:
    """查任务表，不检索文档。"""
    llm = get_chat_model().with_structured_output(DbQuery)
    plan = llm.invoke(
        [
            SystemMessage(
                content=(
                    "根据用户问题决定查任务列表还是单条任务。"
                    "status 只能是 todo / in_progress / done，不确定则留空。"
                    f"{_user_catalog_text()}"
                    "用户要看某一条、谁负责某 id、把某条标为完成，用 get_task。"
                    "用户要一批（进行中的、某人名下的），用 list_tasks。"
                    "只填需要的字段。"
                )
            ),
            *state.get("messages", []),
        ]
    )
    if plan.action == "get_task":
        if plan.task_id:
            raw = get_task(plan.task_id)
        else:
            listed = _parse_json(
                list_tasks(status=plan.status, owner_id=plan.owner_id)
            )
            raw = json.dumps(
                {
                    "error": "missing_task_id",
                    "message": "查询单条任务需要 task_id。下面是按当前条件列出的候选，请指定 id。",
                    "tasks": listed.get("tasks") or [],
                },
                ensure_ascii=False,
            )
    else:
        raw = list_tasks(status=plan.status, owner_id=plan.owner_id)
    return {
        "messages": [AIMessage(content=f"[query_db]\n{raw}")],
        "citations": [],
        "last_route": "query_db",
    }


class WritePlan(BaseModel):
    action: Literal["create_task", "update_task_status"]
    title: str | None = None
    description: str | None = None
    owner_id: str | None = None
    due_date: str | None = None
    task_id: str | None = None
    status: str | None = None


def _is_confirmed(approval: Any) -> bool:
    if approval is True:
        return True
    if isinstance(approval, dict):
        return bool(approval.get("confirmed"))
    return False


def _abort_write(error: str, message: str, **extra: Any) -> dict:
    payload = {"error": error, "message": message, **extra}
    return {
        "messages": [
            AIMessage(content=f"[write]\n{json.dumps(payload, ensure_ascii=False)}")
        ],
        "pending_write": None,
        "last_route": "write",
    }


def _plan_write(state: AgentState) -> WritePlan:
    llm = get_chat_model().with_structured_output(WritePlan)
    return llm.invoke(
        [
            SystemMessage(
                content=(
                    "根据对话整理一条写操作。"
                    "创建待办用 create_task；改状态用 update_task_status。"
                    f"{_user_catalog_text()}"
                    "未指定负责人时不要猜测人名，owner_id 留空，由系统填当前用户。"
                    "status 只能是 todo / in_progress / done。"
                    "不要执行写入，只填字段。"
                )
            ),
            *state.get("messages", []),
        ]
    )


def _validated_write_payload(
    plan: WritePlan, owner_id: str | None
) -> tuple[dict | None, dict | None]:
    """成功 (payload, None)；失败 (None, _abort_write(...))。确认前只读库、不写库。"""
    if plan.action == "update_task_status":
        task_id = (plan.task_id or "").strip()
        new_status = (plan.status or "").strip()
        if not task_id:
            return None, _abort_write("missing_task_id", "更新状态需要 task_id。")
        if new_status not in ALLOWED_STATUS:
            return None, _abort_write(
                "invalid_status",
                "status 只能是 todo / in_progress / done。",
                status=plan.status,
            )
        existing = _parse_json(get_task(task_id))
        if existing.get("error") == "not_found":
            return None, _abort_write("not_found", "找不到该任务。", task_id=task_id)
        current_status = (existing.get("task") or {}).get("status")
        if current_status == new_status:
            return None, _abort_write(
                "status_unchanged",
                f"任务 {task_id} 当前已是 {new_status}，无需修改。",
                task_id=task_id,
                status=new_status,
            )
        return {"task_id": task_id, "status": new_status}, None

    title = (plan.title or "").strip()
    if not title:
        return None, _abort_write("missing_title", "创建待办需要非空标题。")
    if not owner_id:
        return None, _abort_write("missing_owner", "未指定负责人，且当前用户未知。")
    return {
        "title": title,
        "description": plan.description or "",
        "owner_id": owner_id,
        "due_date": plan.due_date,
    }, None


def _commit_write(action: str, payload: dict) -> str:
    if action == "update_task_status":
        return update_task_status(payload["task_id"], payload["status"])
    return create_task(
        title=payload["title"],
        description=payload["description"],
        owner_id=payload["owner_id"],
        due_date=payload["due_date"],
    )


def write_node(state: AgentState) -> dict:
    """整理拟写入内容后 interrupt；确认前不写 SQLite。"""
    plan = _plan_write(state)
    payload, abort = _validated_write_payload(
        plan, plan.owner_id or state.get("user_id") or None
    )
    if abort:
        return abort

    approval = interrupt(
        {
            "type": "write_task",
            "action": plan.action,
            "payload": payload,
            "message": "即将写入待办，请确认或驳回",
        }
    )
    if not _is_confirmed(approval):
        return {
            "messages": [AIMessage(content="已取消写入。")],
            "pending_write": None,
            "last_route": "write",
        }

    raw = _commit_write(plan.action, payload)
    return {
        "messages": [AIMessage(content=f"[write]\n{raw}")],
        "pending_write": None,
        "last_route": "write",
    }


def respond_node(state: AgentState) -> dict:
    """综合 messages 与 citations 生成回复；无出处的制度问答必须拒答。"""
    citations = state.get("citations") or []
    last_route = state.get("last_route") or ""
    citation_block = json.dumps(citations, ensure_ascii=False, indent=2)
    rules = (
        "你是 Northwind Labs 内部工作台助手。"
        "只根据对话里的检索/查库结果回答。"
        "不要调用工具。"
    )
    if last_route == "retrieve" and not citations:
        rules += (
            "当前没有检索命中。必须明确说不知道或没有依据，禁止编造制度、天数或条款。"
        )
    elif citations:
        rules += (
            "制度类回答必须依据 citations，提到文档标题或 chunk_id，不要超出摘录。"
            f"\ncitations:\n{citation_block}"
        )
    llm = get_chat_model()
    reply = llm.invoke(
        [SystemMessage(content=rules), *state.get("messages", [])]
    )
    content = reply.content if isinstance(reply.content, str) else str(reply.content)
    return {
        "messages": [AIMessage(content=content)],
        "last_route": "respond",
        "pending_write": None,
    }
