"""按 data/eval/cases.json 打编译后的图。

    python -m scripts.eval
    python -m scripts.eval E01

需要 .env 的 LLM_API_KEY，以及已经跑过 python -m scripts.ingest。
任务表用临时 SQLite，不改 data/desk.sqlite。知识库仍读 CHROMA_PATH。
无 Key 时跳过并返回 0。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

os.environ["LANGCHAIN_TRACING_V2"] = "false"

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from deskagent.config import get_settings
from deskagent.db import get_task, init_db, list_tasks
from deskagent.graph.graph import get_graph
from deskagent.kb.store import get_collection

CASES_PATH = _ROOT / "data" / "eval" / "cases.json"
REFUSE_HINTS = (
    "不知道",
    "没有依据",
    "未找到",
    "没有检索",
    "无法从",
    "没有出处",
    "没有相关",
    "没有关于",
    "相关信息",
)
TOOL_PREFIXES = ("[search_docs]", "[query_db]", "[write]")
SEED_STATUS = {
    "t_001": "in_progress",
    "t_002": "in_progress",
    "t_003": "todo",
    "t_004": "done",
}


class EvalError(Exception):
    pass


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _turns(case: dict) -> list[dict]:
    if case.get("turns"):
        return list(case["turns"])
    return [case]


def _invoke(graph, payload: dict, config: dict) -> None:
    try:
        graph.invoke(payload, config)
    except GraphInterrupt:
        return


def _snap(graph, config: dict):
    return graph.get_state(config)


def _message_texts(snap) -> list[str]:
    texts: list[str] = []
    for message in snap.values.get("messages") or []:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content:
            texts.append(content)
    return texts


def _joined(texts: list[str]) -> str:
    return "\n".join(texts)


def _last_reply(texts: list[str]) -> str:
    for text in reversed(texts):
        if text.startswith(TOOL_PREFIXES):
            continue
        return text
    return texts[-1] if texts else ""


def _tool_payload(texts: list[str], prefix: str) -> dict:
    marker = prefix + "\n"
    for text in texts:
        if prefix not in text:
            continue
        raw = text.split(marker, 1)[-1] if marker in text else text.split(prefix, 1)[-1]
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _interrupt_payload(snap) -> dict | None:
    interrupts = snap.interrupts or ()
    if not interrupts:
        for task in snap.tasks or ():
            interrupts = getattr(task, "interrupts", None) or ()
            if interrupts:
                break
    if not interrupts:
        return None
    value = interrupts[0].value
    return value if isinstance(value, dict) else {"value": value}


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise EvalError(message)


def _collected_ids(payload: dict) -> set[str]:
    found: set[str] = set()
    for task in payload.get("tasks") or []:
        if isinstance(task, dict) and task.get("id"):
            found.add(task["id"])
    task = payload.get("task")
    if isinstance(task, dict) and task.get("id"):
        found.add(task["id"])
    return found


def _reset_tasks() -> None:
    path = get_settings().db_path
    for suffix in ("", "-wal", "-shm"):
        extra = Path(str(path) + suffix) if suffix else path
        if extra.exists():
            extra.unlink()
    init_db()


def _prepare_runtime() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="deskagent-eval-"))
    os.environ["DB_PATH"] = str(tmp / "desk.sqlite")
    os.environ["CHECKPOINT_PATH"] = str(tmp / "checkpoints.sqlite")
    get_settings.cache_clear()
    get_graph.cache_clear()
    init_db()
    return tmp


def _check_turn(graph, config: dict, turn: dict, *, case_id: str) -> None:
    before = len(list_tasks())
    user_id = turn.get("user_id") or "u_alice"
    _invoke(
        graph,
        {
            "messages": [HumanMessage(content=turn["input"])],
            "user_id": user_id,
        },
        config,
    )
    snap = _snap(graph, config)
    texts = _message_texts(snap)
    joined = _joined(texts)
    reply = _last_reply(texts)
    pending = _interrupt_payload(snap)
    citations = snap.values.get("citations") or []

    for marker in turn.get("expect_markers") or []:
        _require(marker in joined, f"{case_id} 缺少 {marker}")
    for marker in turn.get("forbid_markers") or []:
        _require(marker not in joined, f"{case_id} 不应出现 {marker}")

    if turn.get("must_cite"):
        _require(bool(citations), f"{case_id} 需要 citations")
    cite_doc_id = turn.get("cite_doc_id")
    if cite_doc_id:
        _require(
            any(item.get("doc_id") == cite_doc_id for item in citations),
            f"{case_id} citations 缺少 {cite_doc_id}",
        )

    if turn.get("must_interrupt"):
        _require(pending is not None, f"{case_id} 没有 interrupt")
        _require(snap.next == ("write",), f"{case_id} 应停在 write，实际 next={snap.next}")
        _require(len(list_tasks()) == before, f"{case_id} 确认前任务数变了")
        action = turn.get("interrupt_action")
        if action:
            _require(
                pending.get("action") == action,
                f"{case_id} interrupt.action 应为 {action}，实际 {pending.get('action')}",
            )
        status = turn.get("interrupt_status")
        if status:
            payload = pending.get("payload") or {}
            _require(
                payload.get("status") == status,
                f"{case_id} 拟写入 status 应为 {status}，实际 {payload.get('status')}",
            )
    elif pending is not None and turn.get("seed_statuses_unchanged"):
        payload = pending.get("payload") or {}
        _require(
            pending.get("action") in {"update_task", "delete_task", "create_task"},
            f"{case_id} 批量改写出现未知 action：{pending.get('action')}",
        )
        _require(
            isinstance(payload.get("task_id"), str) and payload.get("task_id"),
            f"{case_id} 批量改写不得一次带多条 id：{payload}",
        )

    if turn.get("refuse"):
        _require(
            any(hint in reply for hint in REFUSE_HINTS),
            f"{case_id} 拒答未出现；reply={reply[:200]}",
        )

    for needle in turn.get("answer_contains") or []:
        blob = reply
        if turn.get("must_cite"):
            quotes = " ".join(str(item.get("quote") or "") for item in citations)
            blob = reply + "\n" + quotes
        _require(needle in blob, f"{case_id} 回答缺少「{needle}」；reply={reply[:200]}")
    for needle in turn.get("answer_not_contains") or []:
        _require(needle not in reply, f"{case_id} 回答不应含「{needle}」；reply={reply[:200]}")

    query_payload = _tool_payload(texts, "[query_db]")
    if turn.get("query_contains_ids"):
        found = _collected_ids(query_payload)
        missing = set(turn["query_contains_ids"]) - found
        _require(not missing, f"{case_id} 查库缺少 {sorted(missing)}；got {sorted(found)}")
    if turn.get("query_equals_ids") is not None:
        found = _collected_ids(query_payload)
        expected = set(turn["query_equals_ids"])
        _require(
            found == expected,
            f"{case_id} 查库应为 {sorted(expected)}，实际 {sorted(found)}",
        )
    if turn.get("query_task_id"):
        task = query_payload.get("task") or {}
        _require(
            task.get("id") == turn["query_task_id"],
            f"{case_id} get_task 应为 {turn['query_task_id']}；{query_payload}",
        )
    if turn.get("query_owner_id"):
        task = query_payload.get("task") or {}
        _require(
            task.get("owner_id") == turn["query_owner_id"],
            f"{case_id} owner_id 应为 {turn['query_owner_id']}；{query_payload}",
        )
    if turn.get("query_error"):
        _require(
            query_payload.get("error") == turn["query_error"],
            f"{case_id} 查库 error 应为 {turn['query_error']}；{query_payload}",
        )

    resume = turn.get("resume")
    if pending is not None and resume is not None:
        _invoke(graph, Command(resume={"confirmed": bool(resume)}), config)
        snap = _snap(graph, config)
        texts = _message_texts(snap)
        joined = _joined(texts)
        _require(snap.next == (), f"{case_id} resume 后未结束")
        if resume:
            _require("[write]" in joined, f"{case_id} 确认后没有写入结果")
        else:
            _require("已取消写入" in joined, f"{case_id} 驳回后没有取消提示")
        after = len(list_tasks())
        if turn.get("db_delta") is not None:
            _require(
                after == before + int(turn["db_delta"]),
                f"{case_id} 任务数应为 {before + int(turn['db_delta'])}，实际 {after}",
            )
        expect_status = turn.get("expect_task_status")
        if expect_status:
            row = get_task(expect_status["task_id"])
            _require(row is not None, f"{case_id} 找不到 {expect_status['task_id']}")
            _require(
                row.get("status") == expect_status["status"],
                f"{case_id} {expect_status['task_id']} status 应为 {expect_status['status']}，实际 {row.get('status')}",
            )
    elif turn.get("db_delta") is not None and resume is None:
        after = len(list_tasks())
        _require(
            after == before + int(turn["db_delta"]),
            f"{case_id} 任务数应为 {before + int(turn['db_delta'])}，实际 {after}",
        )

    if turn.get("seed_statuses_unchanged"):
        for task_id, status in SEED_STATUS.items():
            row = get_task(task_id)
            _require(row is not None, f"{case_id} 种子任务 {task_id} 丢失")
            _require(
                row.get("status") == status,
                f"{case_id} {task_id} 被改成 {row.get('status')}，应为 {status}",
            )


def _run_case(graph, case: dict) -> None:
    _reset_tasks()
    config = {"configurable": {"thread_id": f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"}}
    user_id = case.get("user_id") or "u_alice"
    for turn in _turns(case):
        turn = {**turn, "user_id": turn.get("user_id") or user_id}
        _check_turn(graph, config, turn, case_id=case["id"])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    if not settings.llm_api_key:
        print("SKIP: .env 缺少 LLM_API_KEY，评测未跑。")
        return 0
    if get_collection(reset=False).count() == 0:
        print("ERROR: 知识库为空，先运行 python -m scripts.ingest", file=sys.stderr)
        return 1

    wanted = {item.upper() for item in argv}
    cases = _load_cases()
    if wanted:
        cases = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            print(f"ERROR: 未知用例 {sorted(missing)}", file=sys.stderr)
            return 1

    _prepare_runtime()
    graph = get_graph()
    failed: list[str] = []
    for case in cases:
        case_id = case["id"]
        try:
            _run_case(graph, case)
        except EvalError as exc:
            print(f"FAIL {case_id}: {exc}", flush=True)
            failed.append(case_id)
        else:
            print(f"OK {case_id}", flush=True)

    if failed:
        print(f"ERROR: {len(failed)}/{len(cases)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"OK {len(cases)}/{len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
