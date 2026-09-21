"""业务 SQLite：tasks 表。

建表、导入种子，以及按 status/owner 查询和写入。
users.json 是静态约定（请求头 X-User-Id），不单独建用户表。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from deskagent.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    due_date TEXT,
    created_at TEXT NOT NULL
);
"""

ALLOWED_STATUS = frozenset({"todo", "in_progress", "done"})


def connect() -> sqlite3.Connection:
    """打开 desk.sqlite；父目录不存在则创建。"""
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """创建 tasks 表（已存在则跳过）。"""
    conn.executescript(SCHEMA)
    conn.commit()


def seed_tasks(conn: sqlite3.Connection, seed_path: Path | None = None) -> int:
    """按 id 覆盖写入，ingest 可重复跑而不堆重复行。"""
    settings = get_settings()
    path = seed_path or (settings.seed_dir / "tasks.json")
    rows = json.loads(path.read_text(encoding="utf-8"))
    conn.executemany(
        """
        INSERT OR REPLACE INTO tasks
            (id, title, description, status, owner_id, due_date, created_at)
        VALUES
            (:id, :title, :description, :status, :owner_id, :due_date, :created_at)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def init_db() -> dict[str, int]:
    """建表并导入种子，返回写入条数与表内总行数。"""
    conn = connect()
    try:
        init_schema(conn)
        seeded = seed_tasks(conn)
        total = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
    finally:
        conn.close()
    return {"seeded": seeded, "task_count": total}


def _row_to_task(row: sqlite3.Row) -> dict:
    return dict(row)


def _next_task_id(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT id FROM tasks").fetchall()
    numbers: list[int] = []
    for row in rows:
        task_id = row["id"]
        if not task_id.startswith("t_"):
            continue
        try:
            numbers.append(int(task_id[2:]))
        except ValueError:
            continue
    return f"t_{max(numbers, default=0) + 1:03d}"


def list_tasks(
    status: str | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    """按 status、owner_id 过滤；都不传则返回全部。"""
    conn = connect()
    try:
        sql = "SELECT * FROM tasks"
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_task(row) for row in rows]


def get_task(task_id: str) -> dict | None:
    """按 id 取一条；不存在返回 None。"""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_task(row) if row else None


def create_task(
    title: str,
    description: str | None,
    owner_id: str,
    due_date: str | None,
) -> dict:
    """插入一条 todo，id 为 t_00N，返回新行。"""
    conn = connect()
    try:
        task_id = _next_task_id(conn)
        created_at = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO tasks
                (id, title, description, status, owner_id, due_date, created_at)
            VALUES
                (?, ?, ?, 'todo', ?, ?, ?)
            """,
            (task_id, title, description, owner_id, due_date, created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_task(row)


def update_task_status(task_id: str, status: str) -> dict:
    """更新状态。非法 status 或找不到任务时不写库，返回 error 字段。"""
    if status not in ALLOWED_STATUS:
        return {"error": "invalid_status", "status": status}
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if existing is None:
            return {"error": "not_found", "task_id": task_id}
        conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_task(row)
