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


def update_task(task_id: str, fields: dict) -> str:
    """部分更新标题、描述、负责人、截止日期或状态。找不到或没有可写字段则返回 error JSON。"""
    result = db.update_task(task_id, fields)
    if result.get("error"):
        return json.dumps(result, ensure_ascii=False)
    return json.dumps({"ok": True, "task_id": result["id"]}, ensure_ascii=False)


def delete_task(task_id: str) -> str:
    """删除任务。找不到则返回 error JSON，不写库。"""
    result = db.delete_task(task_id)
    if result.get("error"):
        return json.dumps(result, ensure_ascii=False)
    return json.dumps({"ok": True, "task_id": result["id"]}, ensure_ascii=False)
