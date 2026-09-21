"""阶段一入口：建库、切块入库，并断言演示检索。

    python -m scripts.ingest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows 默认 GBK 会把中文 hits 打成乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from deskagent.db import init_db
from deskagent.kb.ingest import ingest_kb
from deskagent.kb.retrieve import retrieve

DEMO_QUERY = "退款周期"
NEGATIVE_QUERY = "黄金冶炼 COD 限值"


def main() -> int:
    """导入任务种子与知识库，并断言「退款周期」能命中 14 天。"""
    db_stats = init_db()
    kb_stats = ingest_kb(reset=True)
    hits = retrieve(DEMO_QUERY)

    print("db:", json.dumps(db_stats, ensure_ascii=False))
    print("kb:", json.dumps(kb_stats, ensure_ascii=False))
    print("query:", DEMO_QUERY)
    print("hits:", json.dumps(hits, ensure_ascii=False, indent=2))

    ok = any(
        hit.get("doc_id") == "faq-refund" and "14 天" in (hit.get("text") or "")
        for hit in hits
    )
    if not ok:
        print(
            "ERROR: expected faq-refund hit containing 「14 天」",
            file=sys.stderr,
        )
        return 1

    negative = retrieve(NEGATIVE_QUERY)
    print("negative_query:", NEGATIVE_QUERY)
    print("negative_hits:", json.dumps(negative, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
