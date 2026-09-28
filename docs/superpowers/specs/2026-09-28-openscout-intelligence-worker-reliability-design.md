# OpenScout Intelligence 大型 GitHub 同步可靠性设计

## 目标

修复大型 GitHub 仓库同步过程中 Celery Worker 退出后项目永久停留在
`syncing` 的问题，同时避免 solo Worker 在同步任务内把 embedding 请求派回自身，
阻止相同用户、相同仓库和相同时间范围的项目重复创建，并在有证据证明逐条
embedding 是瓶颈时加入受配置控制的有界批处理。

本设计不处理 `/api/events` SSE `429`，不删除现有项目或同步记录，也不改变
GitHub 单来源失败的 `partial`/`failed` 语义。

## 现有证据与边界

已阅读 `CONTRIBUTING.md`、当前 `AGENTS.md` 以及同步链路的直接依赖。

当前本机观察到：

- `celery inspect ping` 没有节点响应，进程表中没有 Celery Worker。
- 实际应用使用的 Redis 6380 可连接；`docsgpt` 队列有 1 个任务，Redis 的
  `unacked` hash 和 `unacked_index` 各有 1 个条目。
- PostgreSQL 中有两个 `langgenius/dify` 项目，最近同步 run 都是
  `running`，项目都是 `syncing`。
- FAISS 1.15、FastEmbed 0.8 与缓存中的 Granite embedding 模型组成的最小
  46 文本子进程测试，在未设置 `KMP_DUPLICATE_LIB_OK` 和设置该变量两种情况下
  都以退出码 0 完成。因此目前没有足够证据把现场 Worker 消失归因于 OpenMP
  或 OOM；实现前必须保留诊断结果，不强行加入全局环境变量。
- 当前 `DelegatedEmbeddings` 已包含 Worker 内本地 embedding 分支，但分支依赖
  `_in_worker()` 的运行时识别；现有测试主要 mock 该判断，缺少真实 Celery
  任务上下文的回归覆盖。
- `claim_project_sync()` 只在下一次 claim 时按启动时间回收旧 run，现有
  `intelligence_sync_runs` 没有 heartbeat 字段或独立回收路径。
- `IntelligenceIndexer.replace_records()` 对每条变更记录调用一次
  `vector_store.add_texts()`；当前模型 batch 默认值为 1。是否需要批处理由
  调用计数和受控基准测试决定，不基于猜测重构。

## 推荐方案

### 1. 先建立可观察的 Worker/embedding 边界

在同步任务进入 FAISS/indexer 前，增加一个任务上下文安全的“本进程 embedding”
边界。同步任务内的本地索引写入必须直接使用
`build_local_embeddings()`，不能通过 Redis 发送 `embed_texts` 并等待结果。
API 查询仍可使用 `EMBEDDINGS_DELEGATE_TO_WORKER`，embedding task 仍直接使用
本地模型。

设计采用现有抽象的最小扩展：

- 保留 `get_embeddings()` 的 API 委派行为。
- 在 `docsgpt/vectorstore/base.py` 增加基于 `contextvars` 的
  `local_embeddings_only()` 上下文管理器；`get_embeddings()` 在该上下文内
  无条件调用 `build_local_embeddings()`。`SyncService.run_incremental()` 和
  `embed_texts` task 分别在自己的调用边界使用该上下文，避免依赖 Celery
  `current_worker_task` 的实现细节；上下文退出后不会污染后续 API 请求。
- 在任务开始、GitHub 文档拉取完成、切块完成、embedding/index 写入前后输出
  阶段日志。日志只包含项目 UUID、仓库名、来源类型、数量和批次进度，不包含
  token、完整文档或 embedding 内容。
- 先用退出码、信号和最小 Worker 运行测试区分 Python 异常、Redis 自等待、
  OpenMP abort 和 OOM。只有确认是 macOS OpenMP 冲突时，才增加仅用于本地
  macOS solo Worker 的启动处理；生产配置不无条件设置
  `KMP_DUPLICATE_LIB_OK`。

### 2. heartbeat 与幂等 stale recovery

新增 `intelligence_sync_runs.last_heartbeat_at`，创建 run 时同时写入
`started_at` 和 `last_heartbeat_at`，并在同步阶段边界以及每个有界 embedding
批次完成后更新。长时间没有新数据的正常任务只要持续 heartbeat，就不会被
回收。

在已有 `run_reconciliation()` 中增加 OpenScout 同步回收 sweep：

1. 在一个数据库事务中，通过 CTE 选出超过
   `INTELLIGENCE_SYNC_STALE_SECONDS` 且 heartbeat 已过期的 `queued/running`
   run，并使用 `FOR UPDATE SKIP LOCKED` 后更新这些行；多个 reconciler 并发
   运行时每一行只有一个事务能够取得锁。
2. 将 run 标记为 `failed`，写入结构化失败信息：
   `Worker exited before completing the sync.`。
3. 只有项目没有更新的活动 run 时，才把项目从 `syncing` 更新到 `failed`。
4. 更新返回计数和日志；重复 sweep 对已终态记录无副作用。

`claim_project_sync()` 使用 heartbeat 而不是只使用原始启动时间判断 stale，
并继续保留当前项目行锁和重复 claim 的 `409` 行为。任务自身的异常收尾仍然
继续传播原始异常；late ack/reject-on-worker-lost 仍由 Celery 负责消息可靠性，
reconciler 负责数据库状态可靠性。

### 3. 项目创建去重

项目身份定义为：

`(user_id, normalized_repository, window_start, window_end)`。

规范化仓库名沿用 `GitHubClient._normalize_repo()` 的 `owner/name` 结果，并在
repository 层生成稳定的 `project_dedupe_key`。数据库增加可唯一约束的去重字段
和部分唯一索引，
对迁移前已经存在的重复项目采取非破坏性处理：保留所有旧行，只选择最早的
一行作为后续创建返回的 canonical 项目，旧重复行不被删除。

key 使用固定格式
`{user_id}\x1f{normalized_repository}\x1f{window_start.isoformat()}\x1f{window_end.isoformat()}`，
并在写入前验证仓库已经是规范化的 `owner/name`，避免不同用户或不同时间范围
发生误冲突。

迁移新增可空 `project_dedupe_key`，并创建
`UNIQUE (project_dedupe_key) WHERE project_dedupe_key IS NOT NULL` 索引。迁移
只为每个既有重复组中最早创建的行填充 key，其余旧重复行保持 `NULL`，因此迁移
不会因现场已有重复项目失败，也不会删除任何历史数据。新建项目始终写入 key，
由该索引保证未来并发请求的最终一致性。

创建流程使用数据库原子冲突处理：

- 首个并发请求创建 canonical 项目并返回 `201`。
- 其他并发请求读取同一 canonical 项目并返回已有项目，使用 `200`，让客户端
  可以安全重试。
- 不同时间范围生成不同去重键，仍允许创建。
- 同一项目的同步继续调用现有 `claim_project_sync()`，最多派发一个 Celery
  任务。

迁移不得删除项目或记录；创建逻辑和数据库约束都必须覆盖未来并发请求。

### 4. 仅在证据充分时批处理 embedding

第一步用 spy/mock 和小型基准确认当前一次 source batch 的
`add_texts()` 调用次数、文本数量、RSS/耗时。若确认逐条调用是大型同步的
实际瓶颈，则在 `IntelligenceIndexer` 内按配置划分有限记录/ chunk 批次：

- 批次大小由新的 OpenScout 配置项控制，并有安全默认值。
- 每次只保留一个有界批次的文本、metadata 和向量映射，不把全仓库文档再复制
  到一个无限列表。
- batch 失败信息包含来源类型和记录 ID，便于定位；原始异常继续传播。
- 未变化记录仍不进入 indexer，不能重新生成 embedding。
- 各批次记录返回的 chunk ID 必须按输入顺序正确映射给 GraphRAG 和审计计数。

若调用计数或基准无法证明瓶颈，则只加入阶段日志和测试，不修改批处理行为。

## 错误与终态语义

- Worker 正常完成：run 为 `complete`/`partial`，项目为 `ready`/`partial`。
- GitHub 单一来源可恢复失败：沿用现有 source-level `partial`/`failed` 逻辑。
- 本地 FAISS、embedding、数据库或保存异常：run 为 `failed`，项目离开
  `syncing`，失败信息保留可诊断消息，原始异常继续向 Celery 传播。
- Worker 被 SIGKILL、SIGABRT、OOM 或机器重启：没有任务收尾时由 heartbeat
  stale sweep 写入 `failed`，项目离开 `syncing`，后续 claim 可以重新开始。
- 任意正常 heartbeat 在 stale 阈值内的长任务不被 sweep 抢占。

## 测试策略（red/green TDD）

按以下顺序添加失败测试并逐项实现：

1. Worker/embedding：真实 task 上下文中不向自身 solo queue 派发 embedding；
   本地 embedding 初始化只发生一次；API 非 Worker 委派行为不变。
2. 诊断：最小 Worker 任务记录阶段和退出状态；若环境可复现 native crash，
   断言信号分类；否则测试只验证不会把未知原因误报为 OpenMP。
3. stale recovery：过期 run 被标记 failed、项目离开 syncing、后续 claim
   成功；新 heartbeat 的长任务不被标记；并发 sweep 幂等。
4. 去重：相同用户/仓库/时间范围的两个并发创建最多一行；不同时间范围仍能
   创建；重复同步最多一个 claim/Celery dispatch。
5. 增量与性能：未变化记录不重新 embedding；若启用批处理，覆盖批次边界、
   记录计数、chunk ID 映射和失败来源。

验证只运行上述同步、Celery、repository、FAISS 和相关迁移测试，以及改动文件
的 Ruff；macOS 测试使用项目要求的 `KMP_DUPLICATE_LIB_OK=TRUE`。不重复执行
完整项目测试套件。

## 预计修改范围

可能修改：

- `docsgpt/intelligence/tasks.py`
- `docsgpt/intelligence/sync_service.py`
- `docsgpt/intelligence/indexing.py`
- `docsgpt/vectorstore/base.py`
- `docsgpt/vectorstore/embeddings_delegated.py`
- `docsgpt/storage/db/repositories/intelligence.py`
- `docsgpt/api/user/intelligence/routes.py`
- `docsgpt/api/user/reconciliation.py`
- `docsgpt/api/user/tasks.py`
- `docsgpt/core/settings.py`
- 一个 OpenScout Alembic migration
- 对应的 `tests/intelligence`、`tests/vectorstore`、`tests/storage` 和 route tests

只有测试证明需要时才修改 macOS Worker 启动入口；不修改 Docker/Kubernetes
生产环境的全局 OpenMP 配置。
