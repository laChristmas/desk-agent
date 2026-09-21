"""把 data/kb/*.md 切块写入向量库。

切块约定：先按 Markdown 标题切开，再按 400 字、overlap 50 滑窗。
chunk_id 形如 faq-refund#2，从 1 起编，供后续引用面板使用。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from deskagent.config import get_settings
from deskagent.kb.store import get_collection, upsert_chunks

# 提取 --- 包裹的 YAML 元数据和剩余正文
FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
# 在 Markdown 标题行前切开，保留标题本身
HEADING_SPLIT_RE = re.compile(r"(?m)(?=^#{1,6}\s+)")


def parse_markdown(path: Path) -> dict[str, Any]:
    """解析一篇 kb 文档；缺少 id/title/category 则报错。"""
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        raise ValueError(f"missing YAML front matter: {path}")
    meta = yaml.safe_load(match.group(1)) or {}
    for key in ("id", "title", "category"):
        if not meta.get(key):
            raise ValueError(f"{path} front matter missing `{key}`")
    return {
        "doc_id": str(meta["id"]),
        "title": str(meta["title"]),
        "category": str(meta["category"]),
        "body": match.group(2).strip(),
        "path": path,
    }


def split_windows(text: str, size: int, overlap: int) -> list[str]:
    """按字数滑窗切块；size/overlap 来自 Settings（默认 400/50）。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def chunk_document(doc: dict[str, Any], size: int, overlap: int) -> list[dict[str, Any]]:
    """先按标题分段，超长段再滑窗；chunk_id 为 `{doc_id}#{从1起的序号}`。"""
    sections = [
        section.strip()
        for section in HEADING_SPLIT_RE.split(doc["body"])
        if section.strip()
    ]

    texts: list[str] = []
    for section in sections:
        texts.extend(split_windows(section, size, overlap))

    chunks: list[dict[str, Any]] = []
    for index, text in enumerate(texts, start=1):
        chunk_id = f"{doc['doc_id']}#{index}"
        chunks.append(
            {
                "id": chunk_id,
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "chunk_id": chunk_id,
                "text": text,
            }
        )
    return chunks


def ingest_kb(*, reset: bool = True) -> dict[str, Any]:
    """读取 data/kb/*.md，切块后写入 Chroma。reset=True 时先清空集合。"""
    settings = get_settings()
    paths = sorted(settings.kb_dir.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"no markdown files in {settings.kb_dir}")

    all_chunks: list[dict[str, Any]] = []
    for path in paths:
        doc = parse_markdown(path)
        all_chunks.extend(
            chunk_document(doc, settings.chunk_size, settings.chunk_overlap)
        )

    collection = get_collection(reset=reset)
    upsert_chunks(collection, all_chunks)
    return {
        "documents": len(paths),
        "chunks": len(all_chunks),
        "collection": collection.name,
    }
