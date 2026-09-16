# OpenScout Stage A 门槛实测摘要

- 结果文件：`routed.holdout.jsonl`
- 题目数：20（封存 holdout）
- 执行器：提交到仓库的 deterministic lexical proxy；不是生产 embedding 或线上延迟测量。
- 非 GraphRAG 延迟排除了 `question_subtype=relational` 的题目。
- token 成本以平均 input/output/total tokens 报告；当前没有货币价格模型。

## 质量门槛

| 门槛 | 实测值 | 要求 | 结果 | 样本数 |
| --- | ---: | ---: | --- | ---: |
| 事实题正确率 | 0.900 | ≥ 0.800 | PASS | 5 |
| 引用精确率 | 0.567 | ≥ 0.900 | FAIL | 20 |
| 比较/综合问题成功率 | 0.890 | ≥ 0.750 | PASS | 10 |
| 非 GraphRAG 平均延迟 | 0.0 ms | ≤ 10000.0 ms | PASS | 18 |
| 五个演示场景无未引用事实 | 5/5 scenarios passed the fixture evidence contract | 所有 fact/statistic claim 有 evidence_ids | PASS | 5 |

## Token 成本

| 项目 | 平均值 | 样本数 |
| --- | ---: | ---: |
| input tokens | 9.350 | 20 |
| output tokens | 40.200 | 20 |
| total tokens | 49.550 | 20 |

## 分题型测量

| 题型 | 样本数 | answer_score | citation_score | latency_ms |
| --- | ---: | ---: | ---: | ---: |
| comparative | 5 | 0.900 | 0.533 | 0.000 |
| comprehensive | 5 | 0.880 | 0.400 | 0.000 |
| factual | 5 | 0.900 | 0.333 | 0.000 |
| temporal | 5 | 0.867 | 1.000 | 0.000 |

## 发布判断：FAIL / 保留为实验

本摘要只记录当前封存快照上的实测值；门槛未通过时不得在 README、简历或演示中宣称 Stage A 已达标。
演示检查：5/5 scenarios passed the fixture evidence contract。运行时路由验收仍由 `tests/integration/test_openscout_stage_a.py` 覆盖。
