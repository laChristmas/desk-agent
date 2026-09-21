"""任务查询与写入工具。阶段二直接写库；interrupt 放到阶段三。"""

from __future__ import annotations

import json

from deskagent import db


def list_tasks(status: str | None = None, owner_id: str | None = None) -> str:
    """按 status、owner 过滤，返回 {"tasks": [...]}。"""
    tasks = db.list_tasks(status, owner_id)
    return json.dumps({"tasks": tasks}, ensure_ascii=False)


def get_task(task_id: str) -> str:
    """按 id 取任务；不存在返回 {"error": "not_found", "task_id": ...}。"""
    task = db.get_task(task_id)
    if not task:
        return json.dumps({"error": "not_found", "task_id": task_id}, ensure_ascii=False)
    return json.dumps({"task": task}, ensure_ascii=False)


def create_task(
    title: str,
    description: str | None,
    owner_id: str,
    due_date: str | None,
) -> str:
    """创建待办，返回 {"ok": true, "task_id": "t_00N"}。"""
    task = db.create_task(title, description, owner_id, due_date)
    return json.dumps({"ok": True, "task_id": task["id"]}, ensure_ascii=False)


def update_task_status(task_id: str, status: str) -> str:
    """更新状态。非法 status 或找不到则返回 error JSON，不写库。"""
    result = db.update_task_status(task_id, status)
    if result.get("error"):
        return json.dumps(result, ensure_ascii=False)
    return json.dumps({"ok": True, "task_id": result["id"]}, ensure_ascii=False)
