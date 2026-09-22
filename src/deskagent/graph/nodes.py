"""图节点：检索、查库、写入（含中断）、回复。

写入在 interrupt 返回之前不得调用 create_task / update_task / delete_task。
LangGraph 从节点开头重跑 resume，因此拟写入内容每次都会再整理一遍，真正写库仍只发生在确认之后。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from deskagent.config import get_settings
from deskagent.db import ALLOWED_STATUS
from deskagent.graph.routing import get_chat_model
from deskagent.graph.state import AgentState
from deskagent.tools.docs import search_docs
from deskagent.tools.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)


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


def _known_user_ids() -> set[str]:
    return {user["id"] for user in _known_users() if user.get("id")}


def _optional_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


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
    status: Literal["todo", "in_progress", "done"] | None = Field(
        default=None,
        description="仅当用户提到状态时填写；未提则 null，不要猜测。",
    )
    owner_id: str | None = Field(
        default=None,
        description="仅当用户点名负责人时填写对应 id；未提则 null，不要填当前用户。",
    )
    task_id: str | None = Field(
        default=None,
        description="仅当用户给出任务 id 时填写；未提则 null，不要猜测。",
    )


def query_db_node(state: AgentState) -> dict:
    """查任务表，不检索文档。"""
    llm = get_chat_model().with_structured_output(DbQuery)
    plan = llm.invoke(
        [
            SystemMessage(
                content=(
                    "根据用户问题决定查任务列表还是单条任务。"
                    "status 只能是 todo / in_progress / done；用户说到进行中、待办、已完成时由你对应到这三个值。"
                    "用户没提到状态、负责人或任务 id 的字段必须为 null，禁止猜测、禁止填当前用户。"
                    f"{_user_catalog_text()}"
                    "用户要看某一条、谁负责某 id、把某条标为完成，用 get_task。"
                    "用户要一批（进行中的、某人名下的），用 list_tasks。"
                    "只填用户明确提到的字段。"
                )
            ),
            *state.get("messages", []),
        ]
    )
    task_id = _optional_text(plan.task_id)
    owner_id = _optional_text(plan.owner_id)
    status = plan.status
    if plan.action == "get_task":
        if task_id:
            raw = get_task(task_id)
        else:
            listed = _parse_json(
                list_tasks(status=status, owner_id=owner_id)
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
        raw = list_tasks(status=status, owner_id=owner_id)
    return {
        "messages": [AIMessage(content=f"[query_db]\n{raw}")],
        "citations": [],
        "last_route": "query_db",
    }


class WritePlan(BaseModel):
    action: Literal["create_task", "update_task", "delete_task"]
    title: str | None = Field(
        default=None,
        description="创建或改标题时填写；否则 null。",
    )
    description: str | None = Field(
        default=None,
        description="创建或改描述时填写；未提则 null，不要用空字符串占位。",
    )
    owner_id: str | None = Field(
        default=None,
        description="创建指定负责人或改负责人时填写对应 id；否则 null。",
    )
    due_date: str | None = Field(
        default=None,
        description="创建或改截止日期时填 YYYY-MM-DD；清空填空字符串；未提则 null。",
    )
    task_id: str | None = Field(
        default=None,
        description="改字段、删除时必须填写用户给出的任务 id；创建则为 null。",
    )
    status: str | None = Field(
        default=None,
        description="改状态时填写 todo / in_progress / done；创建或未改状态则为 null。",
    )


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
                    "创建待办用 create_task；改标题、描述、负责人、截止日期、状态用 update_task；"
                    "删除、删掉、移除任务用 delete_task。"
                    "update_task 与 delete_task 必须带用户给出的 task_id，禁止猜测 id。"
                    "update_task 只填要改的字段，未提到的必须为 null；改状态也走 update_task。"
                    "改负责人时把姓名映射为 owner_id；用户没点名则 owner_id 必须为 null，禁止填当前用户。"
                    f"{_user_catalog_text()}"
                    "未指定负责人时不要猜测人名，owner_id 留空。"
                    "未指定任务id时必须留空，禁止猜测。"
                    "status 只能是 todo / in_progress / done。"
                    "不要执行写入，只填字段。"
                    "只填用户明确提到的字段。"
                )
            ),
            *state.get("messages", []),
        ]
    )


def _validated_write_payload(
    plan: WritePlan, owner_id: str | None
) -> tuple[dict | None, dict | None]:
    """成功 (payload, None)；失败 (None, _abort_write(...))。确认前只读库、不写库。"""
    if plan.action == "delete_task":
        task_id = (plan.task_id or "").strip()
        if not task_id:
            return None, _abort_write("missing_task_id", "删除任务需要 task_id。")
        existing = _parse_json(get_task(task_id))
        if existing.get("error") == "not_found":
            return None, _abort_write("not_found", "找不到该任务。", task_id=task_id)
        task = existing.get("task") or {}
        return {
            "task_id": task_id,
            "title": task.get("title") or "",
        }, None

    if plan.action == "update_task":
        task_id = (plan.task_id or "").strip()
        if not task_id:
            return None, _abort_write("missing_task_id", "修改任务需要 task_id。")
        existing = _parse_json(get_task(task_id))
        if existing.get("error") == "not_found":
            return None, _abort_write("not_found", "找不到该任务。", task_id=task_id)
        task = existing.get("task") or {}
        changes: dict[str, Any] = {}
        if plan.title is not None:
            title = plan.title.strip()
            if not title:
                return None, _abort_write("missing_title", "标题不能为空。")
            changes["title"] = title
        if plan.description is not None:
            changes["description"] = plan.description
        if plan.owner_id is not None:
            owner_id = plan.owner_id.strip()
            if not owner_id:
                return None, _abort_write("missing_owner", "负责人不能为空。")
            known = _known_user_ids()
            if known and owner_id not in known:
                return None, _abort_write(
                    "unknown_owner",
                    "负责人不在已知用户中。",
                    owner_id=owner_id,
                )
            changes["owner_id"] = owner_id
        if plan.due_date is not None:
            due = plan.due_date.strip()
            changes["due_date"] = due or None
        if plan.status is not None:
            new_status = plan.status.strip()
            if new_status not in ALLOWED_STATUS:
                return None, _abort_write(
                    "invalid_status",
                    "status 只能是 todo / in_progress / done。",
                    status=plan.status,
                )
            changes["status"] = new_status
        if not changes:
            return None, _abort_write(
                "missing_fields",
                "修改任务需要标题、描述、负责人、截止日期或状态之一。",
                task_id=task_id,
            )
        filtered: dict[str, Any] = {}
        for key, value in changes.items():
            current_value = task.get(key)
            if key == "description":
                changed = (current_value or "") != (value or "")
            elif key == "due_date":
                changed = (current_value or None) != (value or None)
            else:
                changed = current_value != value
            if changed:
                filtered[key] = value
        if not filtered:
            return None, _abort_write(
                "fields_unchanged",
                f"任务 {task_id} 要改的字段与当前值相同，无需修改。",
                task_id=task_id,
            )
        return {"task_id": task_id, **filtered}, None

    if plan.action != "create_task":
        return None, _abort_write("unsupported_action", "无法识别的写操作。")

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
    if action == "update_task":
        fields = {key: value for key, value in payload.items() if key != "task_id"}
        return update_task(payload["task_id"], fields)
    if action == "delete_task":
        return delete_task(payload["task_id"])
    return create_task(
        title=payload["title"],
        description=payload["description"],
        owner_id=payload["owner_id"],
        due_date=payload["due_date"],
    )


def _write_confirm_message(action: str) -> str:
    if action == "delete_task":
        return "即将删除任务，请确认或驳回"
    if action == "update_task":
        return "即将更新任务，请确认或驳回"
    return "即将写入待办，请确认或驳回"


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
            "message": _write_confirm_message(plan.action),
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
        "不要调用工具，也不要说你将去调用工具。"
    )
    if last_route == "write":
        rules += (
            "上一跳已经处理完写入，结果在对话里。"
            "若出现「已取消写入」，告诉用户没有改库。"
            "若出现 [write] 且 JSON 里 ok 为 true，说明创建、改字段或删除已经成功，并带上 task_id。"
            "若 JSON 里有 error，转述错误原因。"
            "禁止说你无法创建、修改或删除待办、无法调用工具、或还需要再确认一次。"
            "不要编造未出现的字段。"
        )
    elif last_route == "query_db":
        rules += "只根据对话里的查库结果回答。不要检索制度，不要编造任务 id。"
    elif last_route == "retrieve" and not citations:
        rules += (
            "当前没有检索命中。必须明确说不知道或没有依据，禁止编造制度、天数或条款。"
        )
    elif citations:
        rules += (
            "制度类回答必须依据 citations，提到文档标题或 chunk_id，不要超出摘录。"
            f"\ncitations:\n{citation_block}"
        )
    else:
        rules += "只根据对话里已有内容回答，不要编造制度或任务。"
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
