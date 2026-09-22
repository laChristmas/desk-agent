# DeskAgent

Northwind Labs 内部工作台 Agent：按问题检索制度、查询待办、在人工确认后写入 SQLite。

当前仓库覆盖 **数据与检索 → 工具 → LangGraph（含 interrupt）→ FastAPI SSE → React 工作台**。

## 能证明什么

1. 问退款周期会走知识库，回答带文档出处（`faq-refund`，「14 天」）。
2. 问进行中的任务只查 SQLite，不搜文档。
3. 创建、改状态、删除都会在 `write` 节点 `interrupt`；确认前不改库，驳回不写库，确认后才执行对应 SQL。

## 图

```text
START → router → retrieve | query_db | write | respond
retrieve → respond → END
query_db → respond → END
write    → respond → END
```

`interrupt` 只发生在 **write 节点内部**。暂停时拟写入在 interrupt 的 payload 里，用 `graph.get_state(config)` 读取；节点在 `interrupt` 返回之前不会调用 `create_task` / `update_task_status` / `delete_task`。

检索、只读查库、写库的副作用不同，写入必须先停住，因此不用单次 ReAct 把三类工具挂在同一个循环里。

路由规则：

| 用户意图 | 节点 |
|---|---|
| 政策 / 规定 / 出处 | `retrieve`（禁止只靠模型记忆） |
| 任务列表 / 负责人 / 状态 | `query_db` |
| 创建 / 改状态 / 删除 / 关闭 | `write` |
| 寒暄，或总结已经检索/查库的结果 | `respond` |
| 刚检索完且没有出处 | `respond` 拒答，不编条款 |

查库过滤条件（`task_id` / `owner_id` / `status`）只采用模型结构化输出：用户没提到的字段保持为空，代码不会用当前用户去补。创建待办未指定负责人时，owner 用请求头里的当前用户，不写死成某个种子账号。删除必须带用户给出的 `task_id`，找不到则直接返回 `not_found`，不弹出确认。

## HTTP 与前端

`POST /chat`、`POST /chat/resume` 以 SSE 推事件：`meta`（含 `thread_id`）、`interrupt`、`citations`、`message`、`done`。必须带 `X-User-Id`。浏览器 `EventSource` 不能自定义该头，因此前端用 `fetch` + `ReadableStream`。无待确认写入时 `POST /chat/resume` 返回 409。

图是同步 `invoke`，SSE 在整轮结束后才把事件发出去，不是 token 流式。

`web/` 是 Vite + React 工作台：选用户、聊天、展示 citations、确认或驳回写入。开发时把 `/chat`、`/health` 代理到 `127.0.0.1:8000`。

## 目录

```text
desk-agent/
  src/deskagent/
    app.py                 # FastAPI：/chat、/chat/resume、/health
    config.py              # 路径相对仓库根；.env
    db.py                  # tasks 表
    kb/                    # 切块、Chroma、检索
    tools/                 # search_docs / 任务 JSON 工具
    graph/                 # 状态、路由、节点、组图
  web/                     # Vite + React
  data/
    kb/                    # 四篇 Markdown
    seed/                  # users.json、tasks.json
  scripts/
    ingest.py              # 建库 + 入库 + 检索断言
    demo_replay.py         # 三条路径回放（需 LLM）
  tests/test_tasks.py      # 任务工具单测（不调 LLM）
```

运行后生成、已进 `.gitignore`：`data/chroma/`、`data/*.sqlite`、`.env`、`web/node_modules/`、`web/dist/`。

知识库用本地哈希字符 n-gram embedding（不下载 ONNX MiniLM）。检索先按相似度，再用字面短语加权；低于 `RETRIEVE_MIN_SCORE`（默认 0.35）的 hit 丢弃。用户表是静态 `users.json`，不建用户库。

## 环境

- Python 3.11+
- 从仓库根安装：`python -m pip install -e ".[dev]"`
- 复制 `.env.example` 为 `.env`，填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（OpenAI 兼容接口，如通义）
- 前端另需 Node.js：在 `web/` 下 `npm install`

不要把 `.env` 提交进 Git。LangSmith 追踪可选；Key 无效时把 `LANGCHAIN_TRACING_V2` 留空，以免刷 403。

当前默认模型若带思考模式（例如 `qwen3.7-plus`），路由和回复都会先生成 reasoning token，一轮制度问答可能十几秒；这是模型默认行为，不是检索或 SQLite 慢。

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

工作台（两个终端）：

```bash
python -m uvicorn deskagent.app:app --reload --app-dir src
```

```bash
cd web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 `http://127.0.0.1:5173`）。先确认 `/health` 通了再聊天。PowerShell 的 `curl` 是 `Invoke-WebRequest`，探活用 `curl.exe`。

## 测试

不调模型：

```bash
python -m pytest tests/test_tasks.py -q
```

用例使用临时 SQLite，不会改 `data/desk.sqlite`。覆盖：进行中列表、`not_found`、创建、非法 status 不写库、删除已有任务、删除缺失 id。

## 尚未包含

评测集不在本阶段。
