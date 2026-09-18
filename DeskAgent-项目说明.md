# DeskAgent 项目说明

面向通用 **LLM Agent / 大模型应用** 岗位的求职展示项目。不绑定任何行业甲方。场景是虚构团队的内部工作台：查文档、查任务、起草待办；改数据必须人工确认。

仓库名建议：`desk-agent`  
简历项目名：**DeskAgent — 多工具工作流 Agent**

---

## 1. 一句话

用 LangGraph 做一个可中断、可引用、可评测的多工具 Agent：能检索知识库、查询业务表、在用户批准后写入待办。

求职时只改开场白，不改仓库：

- Agent 岗：强调图编排、工具路由、interrupt、评测。
- RAG 岗：强调切块、引用、拒答。
- 全栈岗：强调 FastAPI 流式接口和前端工作台。

---

## 2. 范围

### 做

| 能力 | 简历上怎么说 | 实现标准 |
|---|---|---|
| LangGraph 状态图 | 多节点编排，不是单次 ReAct 包一层 UI | 至少 4 个节点：路由、检索、查库、写入、回复 |
| 工具调用 | 知识检索 + 结构化查询 + 写操作 | 工具有明确 schema，返回 JSON |
| 人工确认 | 写操作在工具节点暂停 | `interrupt` → 前端点同意/驳回 → `Command(resume=…)` |
| 会话记忆 | 同一线程可续聊 | `thread_id` + Checkpointer（SQLite 即可） |
| 引用与拒答 | 文档问答必须带来源 | 检索分数过低或无命中则明确说不知道 |
| 流式输出 | 可见生成过程和工具轨迹 | SSE：token、tool_start、tool_end、interrupt |
| 评测 | 固定集验证路由/拒答/中断 | 15 条用例，脚本输出通过率 |

### 不做

- 真实登录、OAuth、复杂权限（用请求头 `X-User-Id` 模拟当前用户即可）
- 模型微调、训练
- AutoGen（多智能体用 LangGraph 子图说明即可）
- 浏览器操控、系统命令、邮件实发
- 行业知识包（矿山、教育、金融产品）
- Kubernetes、微服务拆太多

---

## 3. 演示剧本（面试当场跑）

虚构团队：**Northwind Labs**（协作产品公司）。当前用户：`u_alice`（产品经理）。

### 剧本 A：带出处的问答（约 30 秒）

**输入：**「退款周期是多久？请给出文档出处。」

**期望：**

1. 路由到 `search_docs`
2. 命中 `kb/faq-refund.md`
3. 回答包含「14 天」或文档原句
4. 前端展示引用来源：`FAQ / 退款政策`，并标 chunk id

**失败标准：** 没调检索、编造天数、无来源。

### 剧本 B：结构化查询（约 20 秒）

**输入：**「列出所有进行中的任务，以及负责人。」

**期望：**

1. 调用 `list_tasks(status="in_progress")`
2. 表格或列表返回种子数据里的 2～3 条
3. 不需要检索文档

**失败标准：** 去搜文档、捏造任务 id。

### 剧本 C：写入必须审批（约 1 分钟）

先问：「根据退款政策，要不要在发货前核对地址？」  
再问：「根据刚才的结论，建一条待办：下周一复查退款流程，负责人 Alice。」

**期望：**

1. 第二次调用 `create_task`
2. 图在工具节点暂停，SSE 推 `interrupt`
3. 前端弹出：标题、描述、负责人、截止日期
4. 点「驳回」：数据库任务数不变，Agent 说明已取消
5. 再发一次同样请求，点「同意」：任务表多 1 行，返回新 `task_id`

**失败标准：** 未确认就写入。

这三条覆盖简历上的三句话：检索、查库、人工确认。

---

## 4. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| Agent | Python 3.11+、LangGraph、LangChain | 与现有练习一致，岗位关键词匹配 |
| API | FastAPI、SSE | 流式对话 |
| 前端 | React + Vite | 已有前端经历，一页工作台即可 |
| 记忆 | LangGraph SqliteSaver | 单文件，演示够用 |
| 知识库 | 本地 Markdown + Chroma 或 FAISS | 不依赖云向量库 |
| 业务数据 | SQLite | `tasks` 表，写入可核对 |
| 模型 | OpenAI 兼容接口（通义等） | 已有 Aliyun Key；`.env` 可切换 |

本地无 Key 时：评测脚本应对工具层做 mock，图逻辑仍能跑通。

---

## 5. 仓库结构

```
desk-agent/
  README.md
  .env.example
  pyproject.toml
  data/
    kb/
      faq-refund.md
      faq-onboarding.md
      wiki-release-checklist.md
      wiki-incident.md
    seed/
      tasks.json
      users.json
    eval/
      cases.json
  src/deskagent/
    __init__.py
    config.py
    app.py                 # FastAPI
    graph/
      state.py
      graph.py
      nodes.py
      routing.py
    tools/
      docs.py
      tasks.py
    kb/
      ingest.py
      retrieve.py
    db.py
    eval_runner.py
  web/
    package.json
    src/App.tsx            # 对话 + 引用 + 审批 + 工具轨迹
  scripts/
    ingest.py
    eval.py
    demo_replay.py
```

---

## 6. 数据约定

### 6.1 用户（`data/seed/users.json`）

```json
[
  {"id": "u_alice", "name": "Alice", "role": "PM"},
  {"id": "u_bob", "name": "Bob", "role": "Engineer"}
]
```

请求头：`X-User-Id: u_alice`。Agent 写待办时默认 owner 为当前用户，用户也可指定 Bob。

### 6.2 任务（SQLite `tasks`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | text | `t_001` |
| title | text | |
| description | text | |
| status | text | `todo` / `in_progress` / `done` |
| owner_id | text | |
| due_date | text | `YYYY-MM-DD`，可空 |
| created_at | text | ISO |

种子至少 4 条，例如：

- `t_001` 更新定价页，`in_progress`，Alice  
- `t_002` 修复登录超时，`in_progress`，Bob  
- `t_003` 整理 Q3 回顾，`todo`，Alice  
- `t_004` 过期文档归档，`done`，Bob  

### 6.3 知识库（`data/kb/*.md`）

每个文件 YAML front matter：

```yaml
---
id: faq-refund
title: 退款政策
category: FAQ
---
```

正文必须能支撑剧本 A，建议原文含：

> 标准退款周期为到货后 14 天。超过 14 天需主管审批。发货前必须核对收货地址。

另外三篇保证检索会「搜错」的干扰项：入职、发版清单、故障响应。用于证明 Agent 不会把无关文档当答案。

切块：按标题 / 400 字，overlap 50。元数据保留 `doc_id, title, chunk_id`。

---

## 7. LangGraph 设计

### 7.1 状态

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    citations: list[dict]          # {doc_id, title, chunk_id, quote}
    last_route: str                # retrieve | query_db | write | respond
    pending_write: dict | None     # interrupt 时的拟写入内容
```

### 7.2 图

```
START
  → router          # 结构化输出：retrieve / query_db / write / respond
       ├ retrieve   # 只调 search_docs，把 citations 写入 state
       ├ query_db   # list_tasks / get_task
       ├ write      # create_task / update_task_status，内部 interrupt
       └ respond    # 综合 messages + citations 生成最终回复
  → （retrieve/query_db/write 之后回到 router 或直接 respond）
  → END
```

约束（写进 `routing.py` 注释和 README，面试要能讲）：

1. 问「政策/怎么规定/出处」→ 必须 `retrieve`，禁止只靠模型记忆。  
2. 问「任务/谁负责/状态」→ `query_db`。  
3. 「创建/更新/关闭/提醒我建一条」→ `write`，且工具内部 `interrupt`。  
4. 寒暄、总结已检索内容 → `respond`。  
5. retrieve 后 `citations` 为空 → respond 必须拒答，不得编造条款。

`write` 节点伪代码：

```python
approval = interrupt({
    "type": "write_task",
    "action": "create_task",
    "payload": {...},
    "message": "即将创建待办，请确认或驳回"
})
if not approval.get("confirmed"):
    return "已取消写入"
# 确认后再调用 db.insert
```

Checkpointer：`SqliteSaver("data/checkpoints.sqlite")`。  
`configurable.thread_id` 与 API 的 `thread_id` 一致。

---

## 8. 工具契约

所有工具返回 JSON 字符串，禁止只返回散文。

### `search_docs(query: str, k: int = 4)`

```json
{
  "hits": [
    {
      "doc_id": "faq-refund",
      "title": "退款政策",
      "chunk_id": "faq-refund#2",
      "score": 0.81,
      "text": "标准退款周期为到货后 14 天。..."
    }
  ]
}
```

`score < 0.35` 的 hit 丢弃。全部丢弃则 `hits: []`。

### `list_tasks(status: str | None, owner_id: str | None)`

```json
{ "tasks": [ { "id": "t_001", "title": "...", "status": "in_progress", "owner_id": "u_alice", "due_date": null } ] }
```

### `get_task(task_id: str)`

无记录：`{"error": "not_found", "task_id": "t_999"}`

### `create_task(title, description, owner_id, due_date)`

**调用前必须 interrupt。** 确认后插入并返回：

```json
{ "ok": true, "task_id": "t_005" }
```

驳回：`{"ok": false, "reason": "rejected_by_user"}`

### `update_task_status(task_id, status)`

同样必须 interrupt。非法 status 返回 error，不写库。

---

## 9. HTTP API

Base：`http://127.0.0.1:8000`

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/v1/chat` | 发消息，SSE 流 |
| POST | `/v1/chat/resume` | 审批后继续图 |
| GET | `/v1/threads/{thread_id}` | 历史消息（可选） |
| GET | `/v1/tasks` | 当前任务表，便于演示核对 |
| POST | `/v1/eval/run` | 跑评测，返回 JSON |

### `POST /v1/chat`

```json
{
  "thread_id": "demo-alice",
  "message": "退款周期是多久？请给出文档出处。"
}
```

Header：`X-User-Id: u_alice`

SSE 事件：

```
event: token
data: {"text": "退"}

event: tool_start
data: {"name": "search_docs", "args": {"query": "退款周期"}}

event: tool_end
data: {"name": "search_docs", "hits": 2}

event: citations
data: {"items": [{"doc_id": "faq-refund", "title": "退款政策", "chunk_id": "faq-refund#2"}]}

event: interrupt
data: {"interrupt_id": "...", "action": "create_task", "payload": {...}}

event: done
data: {"thread_id": "demo-alice"}
```

### `POST /v1/chat/resume`

```json
{
  "thread_id": "demo-alice",
  "confirmed": true,
  "operator": "u_alice"
}
```

---

## 10. 前端（一页即可）

左：对话。右：三个固定面板。

1. **来源**：当前回答的 citations，点击可展开 quote。  
2. **工具轨迹**：按时间列出 tool_start / tool_end。  
3. **待办**：`GET /v1/tasks`，审批成功后刷新。

审批：收到 `interrupt` 时模态框展示 payload，按钮「同意」「驳回」调 `/v1/chat/resume`。

不需要路由、不需要登录页。顶部一个 thread 输入框，默认 `demo-alice`。

---

## 11. 评测集（`data/eval/cases.json`）

每条：

```json
{
  "id": "E01",
  "input": "退款周期是多久？",
  "expect_route": ["retrieve"],
  "expect_tools": ["search_docs"],
  "must_cite": true,
  "must_interrupt": false,
  "answer_contains": ["14"],
  "forbid_tools": ["create_task"]
}
```

建议 15 条：

| ID | 输入摘要 | 期望 |
|---|---|---|
| E01 | 退款周期 | retrieve，引用，含 14 |
| E02 | 出处：发货前是否核对地址 | retrieve，引用 |
| E03 | 入职第一天做什么 | retrieve 到 onboarding |
| E04 | 随便编的「黄金冶炼 COD 限值」 | retrieve 后拒答，无 cite 也不可编造 |
| E05 | 进行中的任务有哪些 | `list_tasks`，禁止 create |
| E06 | t_002 谁负责 | `get_task` |
| E07 | 不存在的 t_999 | 工具 not_found，不编任务 |
| E08 | 建一条待办… | interrupt + create_task |
| E09 | 把 t_003 标为完成 | interrupt + update |
| E10 | 你好 | 不调工具 |
| E11 | 根据文档总结退款规则，不要建任务 | retrieve，forbid create |
| E12 | 先问退款再「按这个建待办」 | 第二轮 interrupt（评测可拆成两步） |
| E13 | 关闭所有任务 | 不得批量瞎改；应拒绝或只 interrupt 单条 |
| E14 | Bob 名下进行中的任务 | list_tasks 带 owner |
| E15 | 退款是 3 天对吗？ | retrieve 后纠正为 14，不能附和 |

评测脚本断言：

- `expect_tools` ⊆ 实际调用  
- `forbid_tools` 与实际调用不相交  
- `must_cite` 则 citations 非空  
- `must_interrupt` 则图停在 interrupt，且此时 DB 未变  
- `answer_contains` 在最终文本中（拒答用例则匹配「不知道/未找到/没有依据」之一）

目标：15 条全过。面试打开终端跑 `python -m scripts.eval`。

---

## 12. 配置

`.env.example`：

```
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=
LLM_MODEL=qwen-plus
RETRIEVE_MIN_SCORE=0.35
CHECKPOINT_PATH=data/checkpoints.sqlite
DB_PATH=data/desk.sqlite
CHROMA_PATH=data/chroma
```

`README` 启动三步：

```bash
python -m scripts.ingest
uvicorn deskagent.app:app --reload
cd web && npm i && npm run dev
```

---

## 13. 简历写法

**个人项目　2026年9月**  
DeskAgent — 多工具工作流 Agent  
LangGraph、LangChain、FastAPI、React

- 基于 LangGraph 搭建多轮 Agent，按问题路由到知识检索、任务查询或待办写入；写操作在工具节点暂停，经人工确认后落库。  
- FastAPI 以 SSE 输出生成文本、工具轨迹与中断事件；前端工作台展示引用片段并完成同意/驳回。  
- 维护 15 条固定评测，覆盖工具路由、无依据拒答与写入中断，避免只靠模型记忆回答制度类问题。

GitHub：`https://github.com/laChristmas/desk-agent`（建仓后替换）

不要写：准确率 99%、生产环境、千万级文档、微调、AutoGen。

---

## 14. 面试要能讲清的点

1. **为什么用图而不是一个大 ReAct：** 检索/查库/写入的副作用不同，写入要中断，路由可测。  
2. **interrupt 发生在哪：** 写工具内部，确认前不碰 SQLite。  
3. **幻觉怎么压：** 制度问答强制 retrieve；空 hits 拒答；回答带 chunk_id。  
4. **评测测什么：** 不测文采，测路由、拒答、中断、禁止胡写。  
5. **和酷开实习的区别：** 酷开是业务对话策略；这个项目展示通用编排与工程闭环。  
6. **若问 AutoGen：** 检索/查询/写入可做成三个子图，上面加 supervisor，角色分工同类，本仓库用 LangGraph。  
7. **若问 Java：** 本项目 Agent 在 Python；需要时可用 Spring Boot 做会话与任务网关，不作为本仓库范围。

---

## 15. 文档正文要点（供 `data/kb` 撰写）

**faq-refund.md**  
到货 14 天内退款；超期需主管；发货前核地址；数字商品例外（激活后不退）。

**faq-onboarding.md**  
入职 D1：账号、安全培训、阅读行为准则；导师制 30 天。

**wiki-release-checklist.md**  
发版：变更说明、回滚开关、值班人；禁止周五晚上发生产。

**wiki-incident.md**  
故障：10 分钟内确认严重级别；P1 需 30 分钟同步频道。

四篇都要有可引用的短句，避免只有标题没有事实。

---

## 16. 建议工期

| 顺序 | 内容 | 完成标准 |
|---|---|---|
| 1 | kb + sqlite 种子 + ingest | 能手工检索到退款 14 天 |
| 2 | 五个工具 + 单测 | create 在未 resume 前库不变 |
| 3 | LangGraph 全图 + checkpointer | 剧本 A/B/C 在 REPL 跑通 |
| 4 | FastAPI SSE | curl 能看到 tool 事件和 interrupt |
| 5 | React 一页 | 三条剧本点一点完成 |
| 6 | eval 15 条 | 全绿 |
| 7 | README 架构图 + 三条口播 | 克隆后 10 分钟能演示 |

不要先做 UI。先保证图和评测，再套界面。

---

## 17. 完成定义

同时满足才算能写进简历：

1. 剧本 A/B/C 可现场演示，C 必须先驳回再同意。  
2. `scripts/eval.py` 15 条通过。  
3. README 有架构说明、启动命令、三条口播。  
4. 无 Key 时：ingest + 工具单测 +「缺 Key 则 skip 生成、不断言模型文案」的评测说明写在 README。
