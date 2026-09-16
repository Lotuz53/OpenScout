# OpenScout AI 架构

OpenScout AI 是构建在 DocsGPT 上的产品情报工作台。DocsGPT 提供 Flask
后端、React/Vite 前端、认证与用户数据存储、向量检索、模型接入以及文档/网页处理
能力；OpenScout 在这些底座上增加面向公开 GitHub 活动的同步、证据契约、受约束
查询和产品比较流程。

## Stage A 数据流

```text
固定 GitHub 快照
      │
      ▼
GitHubClient ──► normalizer ──► IntelligenceRecord
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                    Postgres                DocsGPT 向量索引
                 所有者/覆盖范围              记录级增量切片
                         │                         │
                         └────────────┬────────────┘
                                      ▼
 QueryRequest ──► QueryRouter ──► filters ──► SQL / Hybrid / GraphRAG 路径
                                      │
                                      ▼
                    Claim + Evidence 校验与确定性置信度
                                      │
                                      ▼
                         QueryResult ──► Flask API
                                      │
                                      ▼
 React Overview / Workbench / Evidence / Comparison / Report
```

同步阶段由 `docsgpt/intelligence/github_client.py`、
`sync_service.py` 和 `normalizer.py` 负责。文档、Issue、Issue 评论和 Release
被统一成可追踪的 `IntelligenceRecord`；`indexing.py` 只替换发生变化的记录切片，
而不会因一条记录变化重建整个索引。同步结果同时保留来源类型、时间窗口、数量、
封顶状态和失败原因。

查询入口是 `POST /api/intelligence/query`。`QueryRouter` 将问题归为 factual、
temporal、comparative、aggregate 或 relational，并把低置信度或无效路由回退到
安全的 Hybrid 路径。显式仓库、来源类型和日期过滤在检索前生效。聚合问题使用
白名单统计维度和指标，统计值由 SQL 产生，再用检索结果补充代表性证据；复杂问题
可以经过拆分检索或 GraphRAG，但回退原因会写入 `RetrievalTrace`。

每个 `Claim` 都有稳定 id、类型、可信度和 `evidence_ids`。事实与统计主张没有
有效证据时会被拒绝，`Evidence` 保留标题、摘要、仓库、来源类型、时间和 GitHub
URL。`QueryResult` 将答案、主张、证据、覆盖范围、延迟和检索追踪作为一个稳定
响应交给前端。

## 前端与报告

`frontend/src/intelligence/Overview.tsx` 展示三个固定 Stage A 仓库的覆盖范围和
同步状态；`Workbench.tsx` 发送问题及显式过滤。`ClaimCard.tsx` 和
`EvidencePanel.tsx` 让用户逐条展开证据，`ComparisonMatrix.tsx` 对没有支持证据的
单元格显示“尚未确认”，而 `ReportView.tsx` 复用结构化结果触发 Markdown/PDF
下载。报告由 `ReportService` 先保存结构化 JSON，再由渲染器输出，因此导出不会
重新执行查询，也不会改变来源列表。

## 评估边界

`evaluation/fixtures/stage_a_snapshot.json` 冻结仓库和时间窗口，
`evaluation/dataset/` 保存 60 条开发题与 20 条 holdout 题。当前离线执行器是
可复现的词法 proxy，用来比较 Vector、Hybrid、Hybrid+Rerank 和 routed 配置；
它不是线上模型、embedding、GraphRAG 或网络延迟的替代品。实际门槛结果见
[`stage-a-summary.md`](../../evaluation/results/stage-a-summary.md)。
