# DeskAgent

Northwind Labs 内部工作台 Agent：按问题检索制度、查询待办、在人工确认后写入 SQLite。

当前仓库覆盖 **数据与检索 → 工具 → LangGraph（含 interrupt）**。HTTP API 与前端尚未接入。

## 能证明什么

1. 问退款周期会走知识库，回答带文档出处（`faq-refund`，「14 天」）。
2. 问进行中的任务只查 SQLite，不搜文档。
3. 创建待办会在 `write` 节点 `interrupt`；确认前任务表行数不变，驳回不写库，确认后才 `INSERT`。

## 图

```text
START → router → retrieve | query_db | write | respond
retrieve → respond → END
query_db → respond → END
write    → respond → END
```

`interrupt` 只发生在 **write 节点内部**。暂停时拟写入在 interrupt 的 payload 里，用 `graph.get_state(config)` 读取；节点在 `interrupt` 返回之前不会调用 `create_task` / `update_task_status`。

检索、只读查库、写库的副作用不同，写入必须先停住，因此不用单次 ReAct 把三类工具挂在同一个循环里。

路由规则：

| 用户意图 | 节点 |
|---|---|
| 政策 / 规定 / 出处 | `retrieve`（禁止只靠模型记忆） |
| 任务列表 / 负责人 / 状态 | `query_db` |
| 创建 / 改状态 / 关闭 | `write` |
| 寒暄，或总结已经检索/查库的结果 | `respond` |
| 刚检索完且没有出处 | `respond` 拒答，不编条款 |

查库过滤条件（`task_id` / `owner_id` / `status`）只采用模型结构化输出：用户没提到的字段保持为空，代码不会用当前用户去补。

## 目录

```text
desk-agent/
  src/deskagent/
    config.py              # 路径相对仓库根；.env
    db.py                  # tasks 表
    kb/                    # 切块、Chroma、检索
    tools/                 # search_docs / 任务 JSON 工具
    graph/                 # 状态、路由、节点、组图
  data/
    kb/                    # 四篇 Markdown
    seed/                  # users.json、tasks.json
  scripts/
    ingest.py              # 建库 + 入库 + 检索断言
    demo_replay.py         # 三条路径回放（需 LLM）
  tests/test_tasks.py      # 任务工具单测（不调 LLM）
```

运行后生成、已进 `.gitignore`：`data/chroma/`、`data/*.sqlite`、`.env`。

知识库用本地哈希字符 n-gram embedding（不下载 ONNX MiniLM）。检索先按相似度，再用字面短语加权；低于 `RETRIEVE_MIN_SCORE`（默认 0.35）的 hit 丢弃。用户表是静态 `users.json`，不建用户库。

## 环境

- Python 3.11+
- 从仓库根安装：`python -m pip install -e ".[dev]"`
- 复制 `.env.example` 为 `.env`，填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（OpenAI 兼容接口，如通义）

不要把 `.env` 提交进 Git。LangSmith 追踪可选；Key 无效时把 `LANGCHAIN_TRACING_V2` 留空，以免刷 403。

## 运行

在仓库根目录：

```bash
python -m scripts.ingest
```

会初始化 `data/desk.sqlite`、切块写入 Chroma，并断言「退款周期」能命中含「14 天」的 `faq-refund`。改过 `data/kb/` 后需要再跑。

带模型的三条路径：

```bash
python -m scripts.demo_replay
```

依赖已 ingest、且 `.env` 有 Key。成功时打印四段 `OK`：检索、查库、写入驳回、写入确认。确认那条会在 `desk.sqlite` 里多一条待办；要回到种子数据再跑 `python -m scripts.ingest`。

会话按 `thread_id` 存在 `CHECKPOINT_PATH`（默认 `data/checkpoints.sqlite`）。同一 `thread_id` 换进程也能 `get_state` / `Command(resume=...)` 续跑。

## 测试

不调模型：

```bash
python -m pytest tests/test_tasks.py -q
```

用例使用临时 SQLite，不会改 `data/desk.sqlite`。覆盖：进行中列表、`not_found`、创建、非法 status 不写库。

## 尚未包含

FastAPI / SSE、前端、评测集都不在本阶段。
