"""本地检索。本阶段只返回 hits，不生成答案，避免把空结果编成条款。"""

from __future__ import annotations

from typing import Any

from deskagent.config import get_settings
from deskagent.kb.store import get_collection


def _distance_to_score(distance: float) -> float:
    """把 Chroma cosine distance 转成 0~1 相似度（越大越相关）。"""
    score = 1.0 - float(distance)
    return max(0.0, min(1.0, score))


def _lexical_boost(query: str, text: str) -> float:
    """短中文 query 在哈希向量上容易分不开，用整句/全部 bigram 命中做保底。
    
    不用单字重合率：入职文档里也有「退款」二字，会把干扰项抬过阈值。
    """
    q = query.strip().lower()
    t = text.lower()
    if not q or not t:
        return 0.0
    if q in t:
        return 0.9
    compact = "".join(ch for ch in q if not ch.isspace())
    if len(compact) < 2:
        return 0.0
    bigrams = [compact[i : i + 2] for i in range(len(compact) - 1)]
    hits = sum(1 for gram in bigrams if gram in t)
    if hits == len(bigrams):
        return 0.75
    return 0.0


def retrieve(query: str, k: int = 4) -> list[dict[str, Any]]:
    """返回 {doc_id, title, chunk_id, score, text}。score < 阈值的丢弃。"""
    settings = get_settings()
    collection = get_collection(reset=False)
    total = collection.count()
    if total == 0:
        return []

    # 知识库很小，先取全集再按阈值过滤，避免 top-k 把字面正例挤掉
    result = collection.query(
        query_texts=[query],
        n_results=total,
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits: list[dict[str, Any]] = []
    for text, meta, distance in zip(documents, metadatas, distances):
        meta = meta or {}
        score = max(_distance_to_score(distance), _lexical_boost(query, text or ""))
        if score < settings.retrieve_min_score:
            continue
        hits.append(
            {
                "doc_id": meta.get("doc_id", ""),
                "title": meta.get("title", ""),
                "chunk_id": meta.get("chunk_id", ""),
                "score": round(float(score), 4),
                "text": text or "",
            }
        )
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:k]
