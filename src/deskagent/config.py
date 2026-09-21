"""运行时配置。

路径一律相对仓库根目录解析，避免从不同 cwd 启动时找不到 data/。
LLM 与 checkpoint 本阶段不用，先读入以免后续改 Settings 形状。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# src/deskagent/config.py → 仓库根
ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    """加载仓库根目录的 .env；文件不存在时静默跳过。"""
    load_dotenv(ROOT_DIR / ".env")


def _as_path(value: str) -> Path:
    """相对路径相对仓库根解析，避免依赖当前工作目录。"""
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    """一次读齐的运行时配置，路径都已是绝对路径。"""

    root_dir: Path
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    retrieve_min_score: float
    checkpoint_path: Path
    db_path: Path
    chroma_path: Path
    kb_dir: Path
    seed_dir: Path
    chunk_size: int = 400
    chunk_overlap: int = 50


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局 Settings，进程内只构建一次。"""
    _load_env()
    return Settings(
        root_dir=ROOT_DIR,
        llm_base_url=os.getenv(
            "LLM_BASE_URL",
            "https://ws-v2dyn0zvgyyfbe0u.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        ),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "qwen-max"),
        retrieve_min_score=float(os.getenv("RETRIEVE_MIN_SCORE", "0.35")),
        checkpoint_path=_as_path(
            os.getenv("CHECKPOINT_PATH", "data/checkpoints.sqlite")
        ),
        db_path=_as_path(os.getenv("DB_PATH", "data/desk.sqlite")),
        chroma_path=_as_path(os.getenv("CHROMA_PATH", "data/chroma")),
        kb_dir=ROOT_DIR / "data" / "kb",
        seed_dir=ROOT_DIR / "data" / "seed",
    )
