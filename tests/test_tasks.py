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
    update_task,
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
    data = _parse(update_task("t_003", {"status": "completed"}))
    assert data["error"] == "invalid_status"
    after = _parse(get_task("t_003"))
    assert after["task"]["status"] == before["task"]["status"] == "todo"
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


def test_update_task_fields(seeded_db):
    data = _parse(
        update_task(
            "t_003",
            {
                "title": "整理 Q4 回顾",
                "description": "补充客户反馈",
                "owner_id": "u_bob",
                "due_date": "2026-10-15",
            },
        )
    )
    assert data == {"ok": True, "task_id": "t_003"}
    task = _parse(get_task("t_003"))["task"]
    assert task["title"] == "整理 Q4 回顾"
    assert task["description"] == "补充客户反馈"
    assert task["owner_id"] == "u_bob"
    assert task["due_date"] == "2026-10-15"
    assert task["status"] == "todo"


def test_update_task_clears_due_date_and_keeps_other_fields(seeded_db):
    before = _parse(get_task("t_001"))["task"]
    data = _parse(update_task("t_001", {"due_date": None}))
    assert data == {"ok": True, "task_id": "t_001"}
    after = _parse(get_task("t_001"))["task"]
    assert after["due_date"] is None
    assert after["title"] == before["title"]
    assert after["owner_id"] == before["owner_id"]
    assert after["status"] == before["status"]


def test_update_task_missing_task_is_not_found(seeded_db):
    data = _parse(update_task("t_999", {"title": "不会写入"}))
    assert data == {"error": "not_found", "task_id": "t_999"}
    assert len(db_list_tasks()) == 4


def test_update_task_empty_title_does_not_write(seeded_db):
    before = _parse(get_task("t_002"))["task"]
    data = _parse(update_task("t_002", {"title": "  "}))
    assert data["error"] == "missing_title"
    after = _parse(get_task("t_002"))["task"]
    assert after["title"] == before["title"]


def test_update_task_missing_fields_does_not_write(seeded_db):
    before = _parse(get_task("t_002"))["task"]
    data = _parse(update_task("t_002", {}))
    assert data == {"error": "missing_fields", "task_id": "t_002"}
    after = _parse(get_task("t_002"))["task"]
    assert after == before


def test_update_task_can_set_status(seeded_db):
    before = _parse(get_task("t_003"))["task"]
    data = _parse(update_task("t_003", {"status": "done"}))
    assert data == {"ok": True, "task_id": "t_003"}
    after = _parse(get_task("t_003"))["task"]
    assert after["status"] == "done"
    assert after["title"] == before["title"]
    assert after["owner_id"] == before["owner_id"]
