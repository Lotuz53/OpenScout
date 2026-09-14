# OpenScout AI 实施计划

## 1. 目标与执行方式

本计划将已确认的 [OpenScout AI 设计规格](../specs/2026-09-14-openscout-ai-design.md) 落成一个基于 DocsGPT 的可演示产品。执行目标不是学习 Python 或 React 语法，而是通过 AI 辅助开发掌握 RAG、查询路由、评估和产品决策。

计划分两段：

- 阶段 A：15 个工作日，交付可写入简历的固定三产品版本。
- 阶段 B：5 至 7 个工作日，交付任意公开仓库接入和推广验证版本。

每个任务遵循红绿测试：先增加失败测试，再实现最小功能，运行局部测试，最后运行相关回归测试。每个工作日必须保存功能结果、实验数据和决策记录。

## 2. 已确认的复用点

当前 DocsGPT 主分支已经提供以下能力，不重复开发：

- `docsgpt/parser/remote/github_loader.py`：GitHub 仓库地址规范化、鉴权、限流处理、仓库文件读取。
- `docsgpt/retriever/hybrid_rag.py`：向量与关键词检索的 RRF 融合。
- `docsgpt/retriever/dispatcher.py`：按来源分派检索器和共享 Token 预算。
- `docsgpt/retriever/graph_rag.py` 与 `docsgpt/graphrag/`：GraphRAG 提取、存储、检索和回退。
- `docsgpt/api/user/sources/`：来源创建、同步、状态和检索测试。
- `docsgpt/api/user/artifacts/`：产物元数据和下载基础。
- `frontend/src/App.tsx`、`Navigation.tsx`、Redux 和现有 UI 组件体系。

OpenScout AI 只扩展公开 Issues、评论、Releases、结构化统计、情报查询和专用界面。

## 3. 开发约束

- 后端新模块放入 `docsgpt/intelligence/`，避免把产品情报逻辑混入通用 Retriever。
- 用户 API 放入 `docsgpt/api/user/intelligence/`，统一挂载到 `/api/intelligence`。
- 数据访问通过 `docsgpt/storage/db/repositories/`，路由不直接写 SQL。
- 新 DDL 同时更新 Alembic migration 和 `docsgpt/storage/db/models.py`。
- 后端函数使用类型标注和 Google 风格 docstring；行宽不超过 120。
- 前端新功能放入 `frontend/src/intelligence/`，共享状态使用 Redux。
- 普通统计不调用 LLM；GraphRAG 只用于关系型问题。
- 所有实际指标由固定数据快照和评估脚本生成，禁止手工填写“理想值”。

## 4. 阶段 A：15 个工作日

### 第 1 天：环境基线与现有链路地图

**目标**

确认本地依赖、运行方式和现有检索行为，建立后续实验基线。

**检查与记录**

- 检查 `.venv/`、`.env`、PostgreSQL、pgvector 和 Redis，不重建已经可用的服务。
- 设置 `VECTOR_STORE=pgvector` 和 `GRAPHRAG_ENABLED=true`；确认 Celery worker 可消费默认和 embeddings 队列。
- 运行后端健康检查、前端和一个最小 GitHub 文档来源。
- 对 10 个固定问题保存仅向量检索的结果、延迟和引用。

**涉及文件**

- `.env`：仅本地配置，不提交密钥。
- `docs/openscout/decision-log.md`：记录环境和基线决策。
- `evaluation/baselines/day-01-vector.json`：保存基线结果。

**验证**

```bash
ruff check .
KMP_DUPLICATE_LIB_OK=TRUE python -m pytest tests/test_app_routes.py tests/retriever/test_hybrid.py
cd frontend && npm run build
```

**知识检查**

能够不用代码术语解释：问题如何从界面经过 Embedding、Retriever、上下文和 LLM 变成带引用回答。

### 第 2 天：产品情报数据库模型

**目标**

建立项目、外部记录、同步运行和报告四类持久化对象。

**新增或修改文件**

- 新增 `docsgpt/alembic/versions/0032_openscout_intelligence.py`。
- 修改 `docsgpt/storage/db/models.py`。
- 新增 `docsgpt/storage/db/repositories/intelligence_projects.py`。
- 新增 `docsgpt/storage/db/repositories/intelligence_records.py`。
- 新增 `docsgpt/storage/db/repositories/intelligence_sync_runs.py`。
- 新增 `docsgpt/storage/db/repositories/intelligence_reports.py`。
- 新增 `tests/storage/db/repositories/test_intelligence_*.py`。

**实现要求**

- `intelligence_projects` 保存用户、仓库、状态、时间窗口和最近同步时间。
- `intelligence_records` 保存标准字段及 `content_hash`。
- 唯一键为 `project_id + source_type + external_id`。
- 为 `project_id/source_type`、`created_at`、`updated_at`、`labels` 建索引。
- `intelligence_sync_runs` 保存任务状态、计数、错误摘要和覆盖范围。
- `intelligence_reports` 保存结构化报告、只读分享 token 和版本。

**测试顺序**

1. 写仓库 CRUD、幂等 upsert、哈希不变不更新和用户隔离测试。
2. 运行测试确认失败。
3. 写 migration、Table 定义和 repository。
4. 运行局部测试与 `git diff --check`。

**知识检查**

能够解释为什么结构化记录不能只存在向量数据库，以及元数据过滤如何影响检索正确性。

### 第 3 天：GitHub Issues 与 Releases 客户端

**目标**

在现有 GitHubLoader 基础上增加分页获取 Issues、评论和 Releases 的能力。

**新增或修改文件**

- 新增 `docsgpt/intelligence/__init__.py`。
- 新增 `docsgpt/intelligence/github_client.py`。
- 新增 `docsgpt/intelligence/schemas.py`。
- 新增 `tests/intelligence/test_github_client.py`。
- 仅在必要时小范围修改 `docsgpt/parser/remote/github_loader.py`，提取可复用的请求方法。

**实现要求**

- 复用 `GitHubLoader.normalize_repo` 和现有 token 配置。
- 过滤带 `pull_request` 字段的对象。
- 支持 `since`、分页、每页 100 条和仓库 1,000 条上限。
- 每条 Issue 只获取前 20 条评论。
- 读取 `X-RateLimit-*` 和 `Link` 响应头；限流时返回可恢复错误，不执行长时间阻塞等待。
- 将 API 响应转换为 Pydantic 或 dataclass 标准对象。

**测试场景**

- 多页 Issues。
- Pull Request 过滤。
- Release 时间窗口。
- 评论数量上限。
- 401 降级匿名请求、403/429 限流、404 仓库不存在。
- 缺失字段和空正文。

**知识检查**

能够解释公开 API 的覆盖偏差、分页和限流为什么属于产品体验问题。

### 第 4 天：仓库文档筛选与标准化

**目标**

只收录 README 和仓库内文档，不把整个代码仓库当作竞品资料。

**新增或修改文件**

- 新增 `docsgpt/intelligence/normalizer.py`。
- 修改 `docsgpt/intelligence/github_client.py`。
- 新增 `tests/intelligence/test_normalizer.py`。

**实现要求**

- 文档路径只接受 README 及 `docs/` 下的文本格式。
- Issues、评论、Releases 使用不同标题模板和正文模板。
- 保存仓库、来源类型、原始 URL、日期、状态、标签、版本、评论数和 reaction 数。
- 对 Markdown 做最小清洗，保留代码块、列表和标题层级。
- 生成稳定 `external_id` 和 `content_hash`。

**验证**

使用固定 fixture 输出一份标准化 JSON 快照，人工核对 20 条记录的日期、来源和链接。

**知识检查**

能够解释为什么不同文档类型需要不同切片和元数据，而不是统一按固定字符数处理。

### 第 5 天：首次同步任务与状态 API

**目标**

把采集、标准化、持久化和任务状态串成可恢复的首次同步。

**新增或修改文件**

- 新增 `docsgpt/intelligence/tasks.py`。
- 新增 `docsgpt/intelligence/sync_service.py`。
- 修改 `docsgpt/celeryconfig.py`，注册任务模块。
- 新增 `docsgpt/api/user/intelligence/__init__.py`。
- 新增 `docsgpt/api/user/intelligence/routes.py`。
- 修改 `docsgpt/api/user/routes.py`，注册 namespace。
- 新增 `tests/intelligence/test_sync_service.py`。
- 新增 `tests/api/user/intelligence/test_routes.py`。

**API**

- `POST /api/intelligence/projects`
- `POST /api/intelligence/projects/{id}/sync`
- `GET /api/intelligence/projects/{id}/sync-runs/{run_id}`
- `GET /api/intelligence/projects`
- `GET /api/intelligence/projects/{id}`

**实现要求**

- 创建请求支持幂等键。
- Celery task 可自动重试网络错误，但重试次数有界。
- 单来源失败不回滚其他成功来源。
- 状态返回各类型对象数、失败数、覆盖时间和错误类别。

**知识检查**

能够解释同步“部分成功”为什么优于全部回滚，以及如何向用户表达不完整数据。

### 第 6 天：情报记录进入 DocsGPT 索引

**目标**

将标准化记录转换成 DocsGPT Document，复用现有切片、Embedding 和 pgvector 路径。

**新增或修改文件**

- 新增 `docsgpt/intelligence/indexing.py`。
- 修改 `docsgpt/intelligence/sync_service.py`。
- 新增 `tests/intelligence/test_indexing.py`。
- 按需修改 `docsgpt/parser/chunking_strategies.py`，只增加来源类型入口，不改默认行为。

**实现要求**

- 文档按标题层级切片；Issue 和 Release 默认保持单记录单块，超长时再递归切片。
- 每个 Chunk 保留 `record_id`、`project_id`、仓库、来源类型、时间、版本和 URL。
- `content_hash` 不变时跳过重建。
- 删除或更新记录只影响对应 Chunk。

**验证**

- 同一批数据连续同步两次，第二次新增 Embedding 数量为 0。
- 修改一条 Issue，只重建该记录对应 Chunk。
- 从检索结果点击 URL 能到达正确原文。

**知识检查**

能够解释 Chunk 大小、语义完整性、索引成本和引用粒度之间的权衡。

### 第 7 天：预置三产品与基础情报查询

**目标**

完成三个预置项目和最小“问题到证据”闭环。

**新增或修改文件**

- 新增 `docsgpt/seed/intelligence_projects.py`。
- 新增 `docsgpt/intelligence/query_service.py`。
- 扩展 `docsgpt/api/user/intelligence/routes.py`。
- 新增 `tests/intelligence/test_query_service.py`。

**API**

- `POST /api/intelligence/query`
- `GET /api/intelligence/overview`

**实现要求**

- 默认使用现有 HybridRetriever，返回答案前先暴露候选证据。
- 响应固定包含 `answer`、`claims`、`evidence`、`coverage`、`latency_ms` 和 `trace`。
- 每个 claim 关联 evidence id；无引用事实不进入最终回答。
- 暂不加入 GraphRAG、SQL 统计和复杂路由。

**知识检查**

能区分“检索没找到”和“模型没有使用已找到证据”两类失败。

### 第 8 天：评估框架与向量/混合检索实验

**目标**

先建立可复现评估，再继续优化检索。

**新增文件**

- `evaluation/dataset/questions.jsonl`。
- `evaluation/run_eval.py`。
- `evaluation/metrics.py`。
- `evaluation/configs/vector.yaml`。
- `evaluation/configs/hybrid.yaml`。
- `tests/evaluation/test_metrics.py`。

**实现要求**

- 先完成 40 条开发题和 10 条保留题，后续扩展到 80 条。
- 固定数据快照 id、模型、Embedding、top-k 和 RRF 参数。
- 输出 Recall@5、nDCG@10、正确率、引用准确率、延迟和 Token 用量。
- 结果写入 `evaluation/results/`，文件名包含时间和配置名。

**当日决策门槛**

只有当混合检索在专有名词和版本题上优于向量基线，才将其设为默认；否则记录失败原因并调整关键词索引或切片。

**知识检查**

能够用一个失败样本解释 Recall、Precision 和 nDCG 的区别。

### 第 9 天：时间过滤与 Rerank

**目标**

提高证据精度，解决版本、时间窗口和近似相关结果混入问题。

**新增或修改文件**

- 新增 `docsgpt/intelligence/filters.py`。
- 新增 `docsgpt/intelligence/reranker.py`，优先适配 DocsGPT 现有 post-retrieval stage 接口。
- 修改 `docsgpt/intelligence/query_service.py`。
- 新增 `tests/intelligence/test_filters.py`。
- 新增 `tests/intelligence/test_reranker.py`。

**实现要求**

- 界面显式过滤条件优先于问题文本推断。
- 时间范围在检索前应用，Rerank 在召回后应用。
- Reranker 失败时保持混合检索顺序并记录 fallback。
- 执行第二组实验，比较混合检索与混合检索加 Rerank。

**知识检查**

能够解释 Rerank 为什么不能弥补召回阶段完全漏掉正确证据。

### 第 10 天：查询路由与 SQL 统计

**目标**

将事实、时间、对比、聚合和关系型问题分流，避免用 LLM 做精确计数。

**新增或修改文件**

- 新增 `docsgpt/intelligence/query_router.py`。
- 新增 `docsgpt/intelligence/analytics.py`。
- 新增 `docsgpt/storage/db/repositories/intelligence_analytics.py`。
- 修改 `docsgpt/intelligence/query_service.py`。
- 新增 `tests/intelligence/test_query_router.py`。
- 新增 `tests/intelligence/test_analytics.py`。

**实现要求**

- 路由输出固定 intent、过滤条件、检索策略和置信度。
- 置信度低于 0.65 时回退 Hybrid。
- `aggregate` 只接受白名单统计维度和排序，禁止生成任意 SQL。
- 对比题按项目拆分查询并保持相同时间范围。
- 统计结果携带覆盖数量和上限警告。

**知识检查**

能够解释 Query Routing 如何同时改善正确率、成本和可解释性。

### 第 11 天：选择性 GraphRAG

**目标**

复用 DocsGPT GraphRAG，仅处理关系型和多跳问题。

**新增或修改文件**

- 新增 `docsgpt/intelligence/graph_selection.py`。
- 修改 `docsgpt/intelligence/sync_service.py` 和 `query_service.py`。
- 新增 `tests/intelligence/test_graph_selection.py`。
- 扩展 `tests/intelligence/test_query_service.py`。

**实现要求**

- README、仓库文档、Releases 和每仓库最多 300 条高信号 Issues 进入 GraphRAG。
- 高信号排序使用标准化的评论数与 reaction 数组合。
- GraphRAG 不参与数量和趋势统计。
- GraphRAG 不可用、未完成或超时时自动回退 Hybrid。
- 检索 trace 明确展示是否使用和是否回退。

**实验**

执行第三组实验：统一 Hybrid 与查询路由方案对比，关系题单独报告 GraphRAG 的质量、延迟和成本。

**知识检查**

能够给出一个 GraphRAG 显著有用的问题，以及一个不应使用 GraphRAG 的问题。

### 第 12 天：前端情报首页与工作台

**目标**

完成产品入口、数据透明度和提问控制。

**新增或修改文件**

- 新增 `frontend/src/intelligence/types.ts`。
- 新增 `frontend/src/intelligence/intelligenceService.ts`。
- 新增 `frontend/src/intelligence/intelligenceSlice.ts`。
- 新增 `frontend/src/intelligence/Overview.tsx`。
- 新增 `frontend/src/intelligence/Workbench.tsx`。
- 新增相关组件和 `.test.tsx`。
- 修改 `frontend/src/api/endpoints.ts`、`frontend/src/store.ts`、`frontend/src/App.tsx` 和 `frontend/src/Navigation.tsx`。

**界面要求**

- 首页展示三个产品的数据量、覆盖时间、最近同步和警告。
- 工作台提供产品、时间、来源和问题类型过滤。
- 提供五个稳定推荐问题。
- 加载、空数据、部分同步和错误状态都必须有明确文案。

**验证**

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

**知识检查**

能够解释为什么数据覆盖和更新时间属于核心体验，而不是后台技术信息。

### 第 13 天：证据面板与竞品矩阵

**目标**

让每项结论可验证，并形成区别于普通聊天机器人的展示能力。

**新增文件**

- `frontend/src/intelligence/EvidencePanel.tsx`。
- `frontend/src/intelligence/ClaimCard.tsx`。
- `frontend/src/intelligence/ComparisonMatrix.tsx`。
- 对应测试文件。
- 新增 `docsgpt/intelligence/confidence.py` 和测试。

**实现要求**

- 事实、统计和 AI 推断使用不同标签。
- 每个 claim 展示独立可信度和证据。
- 可信度严格执行设计规格中的确定性规则。
- 矩阵单元格可以展开来源；证据不足显示“尚未确认”。
- 冲突证据同时展示日期和来源。

**知识检查**

能够解释为什么模型自报“95% 可信”不构成可信度，以及本项目如何替代它。

### 第 14 天：报告、异常回退与完整回归

**目标**

生成可下载报告，并完成设计中的主要异常路径。

**新增或修改文件**

- 新增 `docsgpt/intelligence/report_service.py`。
- 扩展 `docsgpt/api/user/intelligence/routes.py`。
- 新增 `frontend/src/intelligence/ReportView.tsx`。
- 新增后端和前端报告测试。

**API**

- `POST /api/intelligence/reports`
- `GET /api/intelligence/reports/{id}`
- `GET /api/intelligence/reports/{id}/download?format=markdown|pdf`

**实现要求**

- 报告保存结构化 JSON，并从同一数据渲染 Markdown/PDF。
- 导出失败不重新执行检索。
- 无引用事实触发一次重生成；再次失败则降级为统计和证据列表。
- 完成限流、部分同步、GraphRAG 回退、冲突和过期数据测试。

**知识检查**

能够解释系统何时应该拒答、回退或展示低可信度，而不是继续生成。

### 第 15 天：阶段 A 验收与简历版本发布

**目标**

达到设计规格的阶段 A 完成定义。

**执行事项**

- 将评估集补齐到 80 条，锁定 20 条保留测试集。
- 运行三组实验并生成最终结果摘要。
- 固定五分钟演示的五个问题和数据快照。
- 完成 `README-openscout.md`、架构说明、限制说明和决策日志。
- 录制演示视频并截取关键界面。
- 准备不夸大实现范围的简历描述。

**完整验证**

```bash
ruff check .
KMP_DUPLICATE_LIB_OK=TRUE python -m pytest
cd frontend && npm run lint
cd frontend && npm run build
cd docs && npm run build
```

**发布门槛**

- 事实题正确率不低于 80%。
- 引用准确率不低于 90%。
- 复杂题成功率不低于 75%。
- 普通问题平均响应时间不超过 10 秒。
- 五个演示场景没有无引用事实性主张。

如未达到门槛，先根据错误分类修复，不修改保留测试题以追求漂亮数字。

## 5. 阶段 B：5 至 7 个工作日

### 第 16 天：任意公开仓库接入

- 在前端增加仓库 URL、时间窗口和数据规模预检。
- 后端验证仓库存在、公开可读，并返回预计对象数量。
- 创建项目后复用阶段 A 同步流程。
- 测试无效 URL、私有仓库、空仓库、归档仓库和超大仓库。

### 第 17 天：增量同步与调度

- 使用最近成功同步时间获取新增或变化记录。
- `content_hash` 不变时跳过索引。
- 删除对象连续两次不存在后退出活跃索引，保留审计记录。
- 复用现有 Celery/RedBeat 调度能力实现手动和每日同步。

### 第 18 天：只读报告分享

- 为报告生成不可猜测的 share token。
- 新增无需登录的只读报告路由和前端页面。
- 分享响应不暴露用户 id、访问 token 或内部 trace 中的敏感字段。
- 支持撤销分享。

### 第 19 至 20 天：用户验证

- 招募至少 5 名产品经理、开发者关系人员或开源维护者。
- 让每人完成同一类竞品研究任务，不先教学答案。
- 记录任务完成率、耗时、证据点击、报告采纳意愿和失败原因。
- 只修复影响核心任务的前三类问题，其他反馈进入后续清单。

### 第 21 至 22 天：推广材料与最终包装（按需）

- 优化首次使用示例和空状态。
- 发布公开 Demo、使用说明和示例报告。
- 更新 README 中的真实用户测试结果。
- 准备 GitHub 项目页、演示 GIF 和中文产品复盘文章。

## 6. 每日工作模板

每天开始：

1. 用 45 至 60 分钟学习当天唯一必要知识点。
2. 用自己的话写出“它解决什么问题、为什么在这里使用”。
3. 先让 AI 生成测试或失败示例，再生成实现。

开发期间：

1. 每次只实现一个可验证行为。
2. 阅读 AI 生成的接口、数据结构和异常分支，不要求记语法。
3. 局部测试通过后再合并到完整链路。

每天结束：

1. 保存当天功能截图或短视频。
2. 更新实验数据或测试结果。
3. 在决策日志记录一个取舍、一个失败案例和第二天目标。
4. 尝试用两分钟向面试官解释当天成果。

## 7. 提交与里程碑策略

- 每个任务至少一个独立提交，提交信息描述用户可见行为。
- 数据库 migration、后端 repository、API、前端和评估不要混成一个巨型提交。
- 第 7 天打 `openscout-baseline` 标签。
- 第 11 天打 `openscout-retrieval-complete` 标签。
- 第 15 天打 `openscout-stage-a` 标签。
- 阶段 B 用户验证完成后打 `openscout-stage-b` 标签。
- 不推送密钥、原始访问 token、用户身份或不可再分发的数据。

## 8. 首日开始前的检查清单

- 确认 Python、Node、Docker、PostgreSQL、pgvector 和 Redis 的现状。
- 确认可用 LLM 与 Embedding 服务及预算。
- 准备 GitHub token，只授予读取公开仓库所需权限。
- 确认本地 `.env` 已被忽略。
- 建立 `evaluation/` 与 `docs/openscout/` 目录。
- 运行现有关键测试并保存基线。
- 不运行 `setup.sh` 或重建已有环境，除非检查确认确实缺失。

## 9. 最终可交付成果

- 可运行的 OpenScout AI 产品。
- 三个预置产品和任意公开仓库的情报空间。
- 80 条人工审核评估集及三组对照实验。
- 带证据、可信度和覆盖说明的竞品报告。
- 真实用户测试记录。
- 架构说明、决策日志、演示视频和在线 Demo。
- 一版诚实、可量化、经得住追问的简历项目描述。
