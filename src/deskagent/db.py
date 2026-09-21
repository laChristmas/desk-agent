"""业务 SQLite：tasks 表。

本阶段只建表并导入种子，供演示核对。list/create 等工具放到阶段二。
users.json 是静态约定（请求头 X-User-Id），不单独建用户表。
"""

from __future__ import annotations

import json
import sqlite3
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
