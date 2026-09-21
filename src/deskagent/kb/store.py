"""Chroma 持久化与 embedding。

默认 ONNX MiniLM 首次要下约 80MB 模型，且偏英文，中文短 query 不稳定。
阶段一用哈希字符 n-gram：离线、可复现，配合 retrieve 的字面加权即可命中「退款 14 天」。
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

from deskagent.config import get_settings

COLLECTION_NAME = "deskagent_kb"
EMBED_DIM = 256


def _embed_one(text: str) -> list[float]:
    """把 1/2/3-gram 哈希到固定维，再 L2 归一化，便于余弦距离。"""
    vec = [0.0] * EMBED_DIM
    text = (text or "").strip().lower()
    if not text:
        return vec
    grams = list(text)
    grams.extend(text[i : i + 2] for i in range(len(text) - 1))
    grams.extend(text[i : i + 3] for i in range(max(len(text) - 2, 0)))
    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % EMBED_DIM
        vec[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vec))
    if norm:
        vec = [value / norm for value in vec]
    return vec


@register_embedding_function
class HashNgramEmbeddingFunction(EmbeddingFunction[Documents]):
    """必须注册 name/config，否则 Chroma 1.5 会回退到默认 ONNX embedding。"""

    def __init__(self) -> None:
        return

    def __call__(self, input: Documents) -> Embeddings:
        """Chroma 入库/查询时调用，对每段文本生成向量。"""
        return [_embed_one(text) for text in input]

    @staticmethod
    def name() -> str:
        """集合配置里保存的 embedding 名称，必须稳定。"""
        return "hash_ngram"

    def get_config(self) -> dict[str, Any]:
        """随集合一起持久化，下次打开才能还原本函数。"""
        return {"dim": EMBED_DIM}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> HashNgramEmbeddingFunction:
        """从已保存的 config 重建实例；本实现无额外参数。"""
        return HashNgramEmbeddingFunction()

    def default_space(self) -> str:
        """与 get_collection 的 hnsw:space=cosine 一致。"""
        return "cosine"


def get_client() -> chromadb.PersistentClient:
    """打开（或创建）本地持久化目录 CHROMA_PATH。"""
    settings = get_settings()
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_path))


def get_collection(*, reset: bool = False) -> chromadb.Collection:
    """取得知识库集合。reset 时删除重建，避免重复入库或旧 embedding 残留。"""
    client = get_client()
    # 重复入库先删集合，避免 chunk 翻倍，也避免旧集合仍绑着 ONNX embedding
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
        embedding_function=HashNgramEmbeddingFunction(),
    )


def upsert_chunks(collection: chromadb.Collection, chunks: list[dict[str, Any]]) -> None:
    """把切块写入集合：documents 存原文，metadata 存 doc_id/title/chunk_id。"""
    if not chunks:
        return
    collection.add(
        ids=[chunk["id"] for chunk in chunks],
        documents=[chunk["text"] for chunk in chunks],
        metadatas=[
            {
                "doc_id": chunk["doc_id"],
                "title": chunk["title"],
                "chunk_id": chunk["chunk_id"],
            }
            for chunk in chunks
        ],
    )
