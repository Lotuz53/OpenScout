# OpenScout AI

OpenScout AI 是一个构建在 [DocsGPT](https://github.com/arc53/DocsGPT) 之上的开源产品情报工作台：它把公开 GitHub 的文档、Issue、评论和 Release 组织成可追溯的证据，并以问题、趋势、产品对比和报告的方式呈现。DocsGPT 提供 Flask/React 应用、认证、用户数据存储、向量检索、模型接入和通用文档处理；OpenScout 是本项目新增的 GitHub 情报数据流、证据优先查询契约、受约束分析、前端工作台、比较矩阵、结构化报告和评估体系。

## 当前结论

Stage A 已完成可重复演示和封存测量，但质量门槛没有全部通过：引用精确率为 **0.567**，低于 **0.900** 要求。因此本版本只作为实验性作品集证据，不宣称“Stage A 已达标”。事实题和复杂问题门槛通过，但不能覆盖引用门槛失败这一结论。

| 指标 | holdout 实测 | 门槛 | 结果 |
| --- | ---: | ---: | --- |
| 事实题正确率 | 0.900 | ≥ 0.800 | PASS |
| 引用精确率 | 0.567 | ≥ 0.900 | FAIL |
| 比较/综合问题成功率 | 0.890 | ≥ 0.750 | PASS |
| 非 GraphRAG 平均延迟 | 0ms | ≤ 10,000ms | PASS* |
| 五个演示场景无未引用事实 | 5/5 | 5/5 | PASS |

\* 延迟来自提交的离线 lexical proxy，不是生产延迟。平均 token 成本为 input **9.350**、output **40.200**、合计 **49.550**；当前没有货币价格模型。完整数值见 [`evaluation/results/stage-a-summary.md`](evaluation/results/stage-a-summary.md)。

## 五分钟演示

离线验收使用固定快照，不访问 GitHub 或真实模型：

```bash
uv sync --group dev
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \
  tests/integration/test_openscout_stage_a.py -q
```

五个场景清单在 [`evaluation/demo/questions.json`](evaluation/demo/questions.json)：发现趋势、查看代表性 Issues、分析 Release 关系、对比三个产品、生成报告。若运行完整 UI，打开 `/intelligence` 后按相同顺序操作：查看概览，进入工作台选择三个仓库，运行推荐问题，展开每张 Claim 的 Evidence，查看比较矩阵，最后在报告视图下载 Markdown 或 PDF。UI 的真实同步需要按项目本地开发环境配置 Postgres、Redis 和 GitHub 凭据；集成测试则始终使用提交的固定 fixture。

## OpenScout 原创工作

- 固定 GitHub 快照、边界受限同步和文档/Issue/评论/Release 的统一记录模型；
- 证据 ID、来源 URL、引用校验、覆盖范围和检索追踪组成的强类型查询结果；
- 显式仓库/来源/日期过滤、确定性统计、问题路由、可选重排和 GraphRAG 回退；
- 主题趋势、三产品证据对比、“尚未确认”单元格以及不重新查询的结构化报告导出；
- 80 条人工审核题目（60 条 dev、20 条 holdout）、冻结快照、三组检索实验和回归门槛。

实现导览见 [`docs/openscout/architecture.md`](docs/openscout/architecture.md)，限制与 PR 截图/短视频清单见 [`docs/openscout/limitations.md`](docs/openscout/limitations.md)，关键决策见 [`docs/openscout/decision-log.md`](docs/openscout/decision-log.md)。

## 三组实验

以下数值均来自 60 条开发题上的提交 fixture；它们用于比较，不是线上质量证明。

| 实验 | Recall@5 | nDCG@10 | answer | citation | faithfulness | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Vector → Hybrid | 0.908 → 0.900 | 0.891 → 0.905 | 0.826 → 0.828 | 0.589 → 0.606 | 0.495 → 0.514 | Hybrid 小幅改善答案/引用 |
| Hybrid → Hybrid+Rerank | 0.900 → 0.900 | 0.905 → 0.905 | 0.828 → 0.828 | 0.606 → 0.606 | 0.514 → 0.514 | 当前 fixture 未测出增益 |
| Unified Hybrid → Routed | 0.900 → 0.908 | 0.905 → 0.891 | 0.828 → 0.826 | 0.606 → 0.589 | 0.514 → 0.495 | 路由未显示收益，保持实验 |

第一组差异表在 [`evaluation/results/vector-vs-hybrid.dev.md`](evaluation/results/vector-vs-hybrid.dev.md)，逐题输入在 [`evaluation/results/vector.dev.jsonl`](evaluation/results/vector.dev.jsonl)、[`evaluation/results/hybrid.dev.jsonl`](evaluation/results/hybrid.dev.jsonl)、[`evaluation/results/hybrid-rerank.dev.jsonl`](evaluation/results/hybrid-rerank.dev.jsonl) 和 [`evaluation/results/routed.dev.jsonl`](evaluation/results/routed.dev.jsonl)。

## 失败案例与抽样偏差

引用门槛失败的逐题记录集中在 `holdout-factual-01`–`05`、`holdout-comparative-01`–`05` 和 `holdout-comprehensive-01`–`05`；答案要点不完整的例子包括 `holdout-temporal-02`、`holdout-temporal-04`、`holdout-comparative-02` 和 `holdout-comprehensive-03`。请在 [`evaluation/results/routed.holdout.jsonl`](evaluation/results/routed.holdout.jsonl) 中复核原始 evidence/citation 字段。失败结果保留在仓库中，未通过编辑封存问题来提高分数。

GitHub Issue 和评论只代表公开社区中的可见活动，受仓库规模、贡献者活跃度、语言、Issue 模板和项目维护习惯影响。Stage A 只抽取三个指定仓库，每仓库最多 1,000 条 Issue、每条最多 20 条评论，所以这些数据不能证明市场需求、商业优先级或完整竞品格局。

## 可重复命令

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python evaluation/run_eval.py \
  --config evaluation/configs/routed.yaml --split holdout --freeze
.venv/bin/python evaluation/summarize.py \
  --release-gates --output evaluation/results/stage-a-summary.md
.venv/bin/python evaluation/check_regression.py \
  --baseline evaluation/results/baseline.json \
  --candidate evaluation/results/stage-a.json --max-drop 0.05
```

holdout 输出已封存；如需改变快照或人工答案，应创建新的 snapshot，而不是覆盖 [`routed.holdout.jsonl`](evaluation/results/routed.holdout.jsonl)。回归基线与候选摘要分别是 [`baseline.json`](evaluation/results/baseline.json) 和 [`stage-a.json`](evaluation/results/stage-a.json)；本次回归检查通过，但它不等价于质量门槛全部通过。

## 项目来源与历史

OpenScout 保留 DocsGPT 的历史提交，以便追溯底层应用、认证、存储、检索和模型接入能力的来源；OpenScout 的新增提交、文档和评估证据在此基础上独立维护。本仓库不是 DocsGPT 官方项目，也不代表 DocsGPT 的发布状态。

## 贡献

请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 了解本地开发、测试和提交要求。欢迎围绕 GitHub 情报同步、证据质量、分析工作台和评估体系提交 Issue 或 Pull Request。
