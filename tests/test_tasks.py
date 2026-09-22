"""任务工具单测：临时库 + 仓库种子，不依赖 API Key。"""

from __future__ import annotations

import json

import pytest

from deskagent.config import get_settings
from deskagent.db import init_db, list_tasks as db_list_tasks
from deskagent.tools.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task_status,
)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "desk.sqlite"))
    get_settings.cache_clear()
    init_db()
    yield
    get_settings.cache_clear()


def _parse(raw: str) -> dict:
    return json.loads(raw)


def test_list_in_progress_matches_seed(seeded_db):
    data = _parse(list_tasks(status="in_progress"))
    assert [task["id"] for task in data["tasks"]] == ["t_001", "t_002"]
    assert {task["status"] for task in data["tasks"]} == {"in_progress"}


def test_get_missing_task_is_not_found(seeded_db):
    data = _parse(get_task("t_999"))
    assert data == {"error": "not_found", "task_id": "t_999"}


def test_create_task_increments_and_is_readable(seeded_db):
    before = len(db_list_tasks())
    data = _parse(
        create_task(
            title="复查退款流程",
            description="下周一复查",
            owner_id="u_alice",
            due_date="2026-09-28",
        )
    )
    assert data["ok"] is True
    assert data["task_id"] == "t_005"
    assert len(db_list_tasks()) == before + 1

    created = _parse(get_task("t_005"))
    assert created["task"]["title"] == "复查退款流程"
    assert created["task"]["status"] == "todo"
    assert created["task"]["owner_id"] == "u_alice"


def test_invalid_status_does_not_write(seeded_db):
    before = _parse(get_task("t_003"))
    data = _parse(update_task_status("t_003", "completed"))
    assert data["error"] == "invalid_status"
    after = _parse(get_task("t_003"))
    assert after["task"]["status"] == before["task"]["status"] == "todo"
    assert len(db_list_tasks()) == 4


def test_update_missing_task_is_not_found(seeded_db):
    data = _parse(update_task_status("t_999", "done"))
    assert data == {"error": "not_found", "task_id": "t_999"}
    assert len(db_list_tasks()) == 4


def test_delete_task_removes_row(seeded_db):
    before = len(db_list_tasks())
    data = _parse(delete_task("t_004"))
    assert data == {"ok": True, "task_id": "t_004"}
    assert len(db_list_tasks()) == before - 1
    assert _parse(get_task("t_004")) == {"error": "not_found", "task_id": "t_004"}


def test_delete_missing_task_is_not_found(seeded_db):
    data = _parse(delete_task("t_999"))
    assert data == {"error": "not_found", "task_id": "t_999"}
    assert len(db_list_tasks()) == 4
