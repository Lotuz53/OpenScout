# OpenScout AI 限制与已知缺口

## 当前发布判断

Stage A holdout 的事实题正确率为 **0.900**（门槛 0.800），比较/综合问题成功率
为 **0.890**（门槛 0.750），非 GraphRAG 平均延迟为 **0ms**（门槛 10,000ms），
五个演示场景的证据契约通过；但引用精确率只有 **0.567**，低于 **0.900** 门槛。
因此本版本保留为实验性作品集证据，不能宣称 Stage A 质量门槛全部通过。

完整逐题结果在 [`routed.holdout.jsonl`](../../evaluation/results/routed.holdout.jsonl)，
门槛计算在 [`stage-a-summary.md`](../../evaluation/results/stage-a-summary.md)。可优先
复核的失败案例包括：

- 引用精确率不足：`holdout-factual-01` 至 `holdout-factual-05`；
- 比较证据混入或遗漏：`holdout-comparative-01` 至 `holdout-comparative-05`；
- 综合证据覆盖不足：`holdout-comprehensive-01` 至 `holdout-comprehensive-05`；
- 答案要点不完整：`holdout-temporal-02`、`holdout-temporal-04`、
  `holdout-comparative-02`、`holdout-comprehensive-03`。

这些是封存结果中的真实失败，不通过修改题目、调低门槛或重写成功文案来消除。

## 数据与测量限制

- 评估使用 deterministic lexical proxy，当前 `latency_ms` 和 token 只反映本地
  fixture 执行；不能代表生产 embedding、LLM、GraphRAG、数据库或 GitHub 网络延迟。
- token 成本目前报告平均 input/output/total tokens（9.350 / 40.200 / 49.550），
  没有绑定供应商价格，因此不声称货币成本。
- 快照只包含 `langgenius/dify`、`infiniflow/ragflow` 和 `labring/FastGPT`，每个
  仓库最多 1,000 条 Issue、每条 Issue 最多 20 条评论，不能外推到所有竞品或完整
  社区活动。
- GitHub Issue 与评论是公开社区信号，不是市场需求、客户数量、付费意愿或商业
  优先级的直接测量。活跃开源贡献者、项目规模、语言和 Issue 提交习惯都会造成
  抽样偏差。
- 80 条题目中 60 条属于开发集，20 条 holdout 已封存；选择方案后不得编辑、重排
  或替换 holdout。需要改变答案或快照时，应建立新的 snapshot 和 holdout split。

## 全量验证环境说明

2026-09-17 使用项目 `.venv` 执行 `KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`，共收集
10,556 项（2 项跳过），结果为 **10,085 passed、451 skipped、22 failed**。13 项
GraphRAG 测试因当前环境未安装 `scipy` 而回退到经典检索，9 项 MCP/BYOM 测试因沙箱
DNS 将测试或供应商地址解析到保留地址 `198.18.2.182` 后被安全 URL 校验拒绝。这些
是现有测试的依赖或网络环境阻断，不属于 OpenScout Stage A 路径；在完整依赖和正常
网络解析的 CI/开发环境中复测前，不将该结果表述为全仓库通过，也不据此改变产品规格。

## 产品范围限制

Stage A 固定为三个仓库和一个时间窗口，仍缺少 Stage B 计划中的任意仓库接入、增量
同步调度、分享权限、反馈闭环和真实用户研究。未知比较单元格会显示“尚未确认”，
不会被推断成“没有该功能”。GraphRAG、重排器和外部模型均可能回退；回退原因必须
在响应追踪中披露。

## PDF 字体部署限制

PDF 渲染器优先读取 `OPENSCOUT_CJK_FONT`，其次查找约定的
`docsgpt/intelligence/resources/fonts/NotoSansCJKsc-Regular.otf` 和运行环境字体，
最后使用 ReportLab 的 `STSong-Light` 回退。当前仓库没有随代码分发的 CJK 字体资产，
所以本地测试可以通过，但不同容器或 PDF 阅读器可能使用不同字体替代。发布前必须
提供经过许可的 CJK 字体文件并通过 `OPENSCOUT_CJK_FONT` 或合规资源目录配置；不得
把 macOS 系统字体直接复制进仓库，也不得将未验证的字体写成已完成的发布证据。

## 截图与短视频清单

以下五张截图已在隔离数据库和本地真实 UI 上捕获，并保留在仓库中作为演示证据；连续
演示视频仍需维护者在目标环境中录制，不把未捕获的视频写成已完成证据：

- [x] `docs/openscout/evidence/01-overview.png`：概览页显示三个仓库覆盖范围；
- [x] `docs/openscout/evidence/02-workbench-query.png`：工作台问题、过滤器和结果摘要；
- [x] `docs/openscout/evidence/03-evidence-panel.png`：展开主张并打开 GitHub 来源；
- [x] `docs/openscout/evidence/04-comparison.png`：三产品矩阵及“尚未确认”单元格；
- [x] `docs/openscout/evidence/05-report-download.png`：六章节报告与 Markdown/PDF 下载；
- [x] `docs/openscout/evidence/06-shared-report.png`：只读分享报告显示覆盖范围和来源；
- [ ] `docs/openscout/evidence/stage-a-demo.mp4`：不超过五分钟的连续演示，覆盖上述五个场景。
