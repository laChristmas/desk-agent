"""HTTP 入口：把已编译的图接到 SSE。不在这里直接写 SQLite。

    python -m uvicorn deskagent.app:app --reload --app-dir src
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from pydantic import BaseModel, Field

from deskagent.graph.graph import get_graph

app = FastAPI(title="DeskAgent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    confirmed: bool = Field(description="true 写入，false 取消")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _require_user(x_user_id: str | None) -> str:
    user_id = (x_user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="缺少请求头 X-User-Id")
    return user_id


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _last_ai_text(values: dict) -> str:
    for message in reversed(values.get("messages") or []):
        kind = getattr(message, "type", None)
        if kind == "ai" or isinstance(message, AIMessage):
            return _message_text(message)
        if isinstance(message, dict) and message.get("role") in {"ai", "assistant"}:
            return _message_text(message)
    return ""


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


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _invoke_turn(
    *,
    thread_id: str,
    user_id: str,
    message: str | None,
    confirmed: bool | None,
) -> list[dict]:
    graph = get_graph()
    config = _config(thread_id)
    try:
        if confirmed is not None:
            snap = graph.get_state(config)
            if not _interrupt_payload(snap):
                raise HTTPException(status_code=409, detail="当前会话没有待确认的写入")
            graph.invoke(Command(resume={"confirmed": confirmed}), config)
        else:
            graph.invoke(
                {
                    "messages": [HumanMessage(content=message or "")],
                    "user_id": user_id,
                },
                config,
            )
    except GraphInterrupt:
        pass
    except HTTPException:
        raise

    snap = graph.get_state(config)
    pending = _interrupt_payload(snap)
    if pending:
        return [{"type": "interrupt", "pending": pending}, {"type": "done"}]

    values = snap.values or {}
    events: list[dict] = []
    citations = values.get("citations") or []
    if citations:
        events.append({"type": "citations", "citations": citations})
    events.append({"type": "message", "content": _last_ai_text(values)})
    events.append({"type": "done"})
    return events


async def _stream(thread_id: str, events: list[dict]):
    yield _sse({"type": "meta", "thread_id": thread_id})
    for event in events:
        yield _sse(event)


def _sse_response(thread_id: str, events: list[dict]) -> StreamingResponse:
    return StreamingResponse(
        _stream(thread_id, events),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/chat")
async def chat(
    body: ChatRequest,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> StreamingResponse:
    user_id = _require_user(x_user_id)
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")
    thread_id = (body.thread_id or "").strip() or str(uuid.uuid4())
    events = await asyncio.to_thread(
        _invoke_turn,
        thread_id=thread_id,
        user_id=user_id,
        message=message,
        confirmed=None,
    )
    return _sse_response(thread_id, events)


@app.post("/chat/resume")
async def chat_resume(
    body: ResumeRequest,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> StreamingResponse:
    user_id = _require_user(x_user_id)
    thread_id = (body.thread_id or "").strip()
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id 不能为空")
    events = await asyncio.to_thread(
        _invoke_turn,
        thread_id=thread_id,
        user_id=user_id,
        message=None,
        confirmed=body.confirmed,
    )
    return _sse_response(thread_id, events)
