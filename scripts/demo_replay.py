"""三条路径回放：检索带出处、查任务不搜文档、写入前 interrupt。

    python -m scripts.demo_replay

需要 .env 里的 LLM_API_KEY，以及已经跑过 python -m scripts.ingest。
确认写入会在 desk.sqlite 里多一条待办；驳回那条不会写库。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from deskagent.config import get_settings
from deskagent.db import list_tasks
from deskagent.graph.graph import get_graph

USER_ID = "u_alice"


class ReplayError(Exception):
    pass


def _thread(name: str) -> dict:
    return {"configurable": {"thread_id": f"demo-{name}-{uuid.uuid4().hex[:8]}"}}


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


def _joined(snap) -> str:
    return "\n".join(_message_texts(snap))


def _tool_payload(snap, prefix: str) -> dict:
    marker = prefix + "\n"
    for text in _message_texts(snap):
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
        raise ReplayError(message)


def _run_retrieve(graph) -> None:
    config = _thread("retrieve")
    _invoke(
        graph,
        {
            "messages": [HumanMessage("退款周期是多久？请给出文档出处。")],
            "user_id": USER_ID,
        },
        config,
    )
    snap = _snap(graph, config)
    citations = snap.values.get("citations") or []
    quote = " ".join(str(item.get("quote") or "") for item in citations)
    joined = _joined(snap)
    _require(snap.next == (), "retrieve 未跑完")
    _require("[search_docs]" in joined, "retrieve 没有调用 search_docs")
    _require(
        any(item.get("doc_id") == "faq-refund" for item in citations),
        "citations 缺少 faq-refund",
    )
    blob = quote + "\n" + joined
    _require(
        "14 天" in blob or "14天" in blob,
        "未出现「14 天」；citations="
        + json.dumps(citations, ensure_ascii=False),
    )
    print("OK retrieve", json.dumps({"last_route": snap.values.get("last_route")}, ensure_ascii=False))
    print(joined.splitlines()[-1][:300])


def _run_query(graph) -> None:
    config = _thread("query")
    _invoke(
        graph,
        {
            "messages": [HumanMessage("现在有哪些进行中的任务？")],
            "user_id": USER_ID,
        },
        config,
    )
    snap = _snap(graph, config)
    joined = _joined(snap)
    payload = _tool_payload(snap, "[query_db]")
    found = {
        task.get("id")
        for task in (payload.get("tasks") or [])
        if isinstance(task, dict)
    }
    if payload.get("task"):
        found.add(payload["task"].get("id"))
    expected = {task["id"] for task in list_tasks(status="in_progress")}
    _require(snap.next == (), "query_db 未跑完")
    _require("[query_db]" in joined, "query_db 没有查库")
    _require("[search_docs]" not in joined, "query_db 路径误调了 search_docs")
    _require(not (snap.values.get("citations") or []), "query_db 不应留下 citations")
    _require("t_001" in joined and "t_002" in joined, "进行中任务应包含 t_001 / t_002")
    _require(
        expected <= found,
        f"进行中任务应为 {sorted(expected)}，查库得到 {sorted(found)}；"
        + json.dumps(payload, ensure_ascii=False),
    )
    print("OK query_db", json.dumps({"last_route": snap.values.get("last_route")}, ensure_ascii=False))
    print(joined.splitlines()[-1][:300])


def _run_write(graph, *, confirmed: bool) -> None:
    label = "write-confirm" if confirmed else "write-reject"
    config = _thread(label)
    before = len(list_tasks())
    _invoke(
        graph,
        {
            "messages": [
                HumanMessage("帮我建一条待办：发货前核对收货地址")
            ],
            "user_id": USER_ID,
        },
        config,
    )
    snap = _snap(graph, config)
    pending = _interrupt_payload(snap)
    _require(pending is not None, f"{label} 没有 interrupt")
    _require(snap.next == ("write",), f"{label} 应停在 write，实际 next={snap.next}")
    _require(len(list_tasks()) == before, f"{label} 确认前任务数变了")
    print(
        "OK interrupt",
        json.dumps(
            {"thread": label, "pending": pending, "task_count": before},
            ensure_ascii=False,
        ),
    )

    _invoke(graph, Command(resume={"confirmed": confirmed}), config)
    snap = _snap(graph, config)
    after = len(list_tasks())
    joined = _joined(snap)
    last = (_message_texts(snap) or [""])[-1]
    _require(snap.next == (), f"{label} resume 后未结束")
    if confirmed:
        _require(after == before + 1, f"确认后任务数应为 {before + 1}，实际 {after}")
        _require("[write]" in joined, "确认后没有写入结果")
        _require(
            "无法创建" not in last and "无法调用" not in last,
            f"确认后回复与写入结果矛盾：{last[:200]}",
        )
    else:
        _require(after == before, "驳回后任务数不应变化")
        _require("已取消写入" in joined, "驳回后没有取消提示")
        _require(
            "无法创建" not in last and "无法调用" not in last,
            f"驳回后回复与写入结果矛盾：{last[:200]}",
        )
    print(
        "OK",
        label,
        json.dumps({"task_count": after, "last": joined.splitlines()[-1][:200]}, ensure_ascii=False),
    )


def main() -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        print("ERROR: .env 缺少 LLM_API_KEY", file=sys.stderr)
        return 1

    graph = get_graph()
    try:
        _run_retrieve(graph)
        print()
        _run_query(graph)
        print()
        _run_write(graph, confirmed=False)
        print()
        _run_write(graph, confirmed=True)
    except ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
