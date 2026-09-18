# DeskAgent 进度规划

项目共 **6 个阶段**。按顺序做，上一阶段的完成标准没达到，不要开始下一阶段。

目标不是「把目录搭全」，而是每一阶段结束时都有能演示或能断言的结果。全部完成后才写进简历。

| 阶段 | 名称 | 建议产出 | 本阶段结束时你能证明什么 |
|---|---|---|---|
| 1 | 基础与数据 | 仓库 + 种子知识库/任务表 + 入库脚本 | 文档能被切块检索到「退款 14 天」 |
| 2 | 工具与存储 | 五个工具 + SQLite + 单测 | 查任务、写任务在代码里可测，不经过模型 |
| 3 | Agent 图 | LangGraph 全图 + Checkpointer | REPL 跑通三条面试剧本 |
| 4 | 后端接口 | FastAPI + SSE | curl 能看到流式文本、工具事件、中断 |
| 5 | 前端工作台 | React 单页 | 鼠标点完三条剧本，含驳回/同意 |
| 6 | 评测与交付 | 15 条评测 + README | 评测全绿，别人能按文档 10 分钟跑起来 |

---

## 阶段 0（不单独算工期）

开工前固定这些，后面不再改项目定位：

- 仓库名：`desk-agent`
- 场景：虚构团队 Northwind Labs 内部工作台
- 不做：登录体系、微调、AutoGen、行业知识包

---

## 阶段 1：基础与数据

**目标：** 项目能跑、演示数据齐、检索链路不依赖 Agent。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| 仓库骨架 | `pyproject.toml`、包名 `deskagent`、`.env.example`、`.gitignore` |
| 配置 | `config.py`：模型、分数阈值、SQLite/向量库路径 |
| 知识库原文 | `data/kb/` 四篇：退款政策、入职、发版清单、故障响应；含 YAML 头 |
| 种子数据 | `users.json`（Alice / Bob）、`tasks.json`（至少 4 条，含进行中/待办/完成） |
| 业务库 | `db.py`：建表 `tasks`、导入种子 |
| 入库与检索 | `ingest.py` + `retrieve.py`：切块、写入向量库、按 query 返回 hits |

### 完成标准

- `python -m scripts.ingest` 无报错
- 查询「退款周期」能命中 `faq-refund`，文本含 **14 天**
- 查询无关问题（例如编造的排放限值）可以命中很差或空 hits，不得假写答案（本阶段还没有 LLM）

### 未完成则不算过

只有空目录或 Markdown，没有 ingest、不能本地检索。

---

## 阶段 2：工具与存储

**目标：** Agent 将要调用的工具全部可用，并且用测试锁住「读写边界」。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| `tools/docs.py` | `search_docs(query, k)`：JSON hits；低于阈值丢弃 |
| `tools/tasks.py` | `list_tasks`、`get_task`、`create_task`、`update_task_status` |
| 数据库封装 | 插入/更新/按 status·owner 过滤；非法 status 返回 error |
| 单测 | 读工具、not_found、写入成功、非法状态不写库 |

说明：`interrupt` 放在阶段 3 的图节点里。本阶段 `create_task` / `update_task_status` 是「确认之后真正写库」的函数，测试直接调用它们。

### 完成标准

- `list_tasks(status="in_progress")` 只返回种子里进行中的任务
- `get_task("t_999")` 返回 `not_found`，不编数据
- `create_task(...)` 后任务数 +1，能查到新 id
- 单测可独立跑，不需要 API Key

### 未完成则不算过

工具只 print、返回散文、或写库没有测试。

---

## 阶段 3：Agent 图

**目标：** LangGraph 成为项目核心。三条面试剧本在命令行可复现。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| `graph/state.py` | messages、user_id、citations、last_route、pending_write |
| `graph/routing.py` | 路由到 retrieve / query_db / write / respond 的规则与结构化输出 |
| `graph/nodes.py` | 四个节点：检索写 citations；查库调 list/get；写入前 `interrupt`；回复 |
| `graph/graph.py` | 组图、边、结束条件 |
| Checkpointer | SqliteSaver，按 `thread_id` 续聊 |
| REPL 演示 | `demo_replay.py` 或 notebook：按固定输入跑 A/B/C |

### 本阶段必须实现的功能

1. 问政策/出处 → 必须走 retrieve，citations 写入 state  
2. 问任务列表/负责人 → query_db，不搜文档  
3. 创建/改状态 → write 节点 `interrupt`，**resume 前 SQLite 行数不变**  
4. retrieve 空 hits → respond 拒答，不编条款  
5. 同一 `thread_id` 第二轮能根据上一轮结论建待办  

### 完成标准（三条剧本）

| 剧本 | 输入要点 | 必须看到 |
|---|---|---|
| A | 退款周期 + 出处 | 调用 `search_docs`，回答含 14，有 citation |
| B | 列出进行中任务 | 调用 `list_tasks`，id 与种子一致 |
| C | 建待办 | 先 interrupt；模拟驳回则不写库；再同意则多 1 行 |

### 未完成则不算过

只会 `create_agent` 挂三个工具、没有独立 write 中断、或中断前已经 insert。

---

## 阶段 4：后端接口

**目标：** 浏览器和 curl 能驱动同一张图，事件可给前端用。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| FastAPI 入口 | `app.py`、CORS、`X-User-Id` |
| `POST /v1/chat` | SSE：`token` / `tool_start` / `tool_end` / `citations` / `interrupt` / `done` |
| `POST /v1/chat/resume` | `{thread_id, confirmed}` 继续图 |
| `GET /v1/tasks` | 当前任务表，供演示核对 |
| （可选）`GET /v1/threads/{id}` | 历史消息 |

### 完成标准

用 curl（或 httpie）不打开前端即可：

1. 发剧本 A，流里出现 `tool_start: search_docs` 和 `citations`  
2. 发剧本 C，流里出现 `interrupt`，此时 `GET /v1/tasks` 条数不变  
3. `resume confirmed=false` 后仍不变；`confirmed=true` 后条数 +1  

### 未完成则不算过

只有同步 JSON 最终回复、没有 interrupt 事件、或 resume 接口不存在。

---

## 阶段 5：前端工作台

**目标：** 面试可以只开浏览器演示，不必盯终端。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| 对话区 | 发消息、展示助手回复、thread_id 可改（默认 `demo-alice`） |
| 来源面板 | 渲染 citations：标题 + chunk + 摘录 |
| 工具轨迹 | 按时间列出工具名与参数摘要 |
| 审批弹窗 | 收到 interrupt 后展示 payload；同意 / 驳回调 resume |
| 待办面板 | 拉取 `/v1/tasks`，写入成功后刷新 |

### 完成标准

不碰 curl，只用页面：

1. 问退款周期 → 右侧出现退款政策来源  
2. 问进行中任务 → 轨迹里有 `list_tasks`，答案与右侧待办一致  
3. 建待办 → 弹窗 → 驳回（列表不变）→ 再发 → 同意（列表 +1）  

### 未完成则不算过

只有一个聊天框、看不到来源/轨迹/审批，或审批只是 `alert` 没有调 resume。

---

## 阶段 6：评测与交付

**目标：** 项目从「能演示」变成「能写进简历、能给别人复现」。

### 本阶段模块

| 模块 | 要完成的功能 |
|---|---|
| `data/eval/cases.json` | 15 条：E01–E15（路由、引用、拒答、中断、禁止胡写） |
| `scripts/eval.py` | 跑图、断言工具集合、citations、interrupt、关键词 |
| README | 架构说明、启动三步、三条口播、无 Key 时如何跑单测 |
| 简历定稿 | 三句话与仓库能力一致，不写没做的指标 |

### 完成标准

- `python -m scripts.eval`：**15 条全部通过**  
- 无 API Key 时：ingest + 阶段 2 单测仍可通过；README 写明生成类用例需 Key  
- 克隆后按 README，约 10 分钟能再现剧本 A/B/C  

### 未完成则不算过

只有手工感觉「还行」、没有评测脚本，或 README 无法让别人跑起来。

---

## 阶段依赖（不要跳）

```
1 基础与数据
    → 2 工具与存储
        → 3 Agent 图
            → 4 后端接口
                → 5 前端工作台
                    → 6 评测与交付
```

3 依赖 2（图调工具）。  
4 依赖 3（接口只是把图流式化）。  
5 依赖 4（页面只消费 SSE）。  
6 依赖 3（评测打图）；前端不是评测前提，但交付时 5 应已完成。

允许并行的只有：**阶段 5 的页面骨架** 可在阶段 4 后半与接口联调同时做；页面在 4 的 SSE 事件未定时不要接假数据充数。

---

## 建议不要拆进这 6 段的事项

下列若要做，放在 **简历投出之后** 的增强，不算本项目交付范围：

- Spring Boot 网关  
- 登录 / JWT  
- LangSmith 等云追踪  
- 多智能体 supervisor 拆分子图  
- 更多知识库或真实业务接入  

---

## 简历写入条件（对应阶段 6 结束）

同时满足才把 DeskAgent 写上简历：

1. 阶段 3 三条剧本在 REPL 可复现  
2. 阶段 5 浏览器可演示驳回再同意  
3. 阶段 6 评测 15/15  
4. README 可独立复现  

未完成阶段 3，不要把「LangGraph 多工具 Agent」写进简历。  
未完成阶段 5，面试只能盯日志，不建议作为主展示项目。
