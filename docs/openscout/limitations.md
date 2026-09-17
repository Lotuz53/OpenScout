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

2026-09-17 使用项目 `.venv` 在非沙箱环境执行
`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest --postgresql-port=55433`，结果为
**10,088 passed、451 skipped、22 failed、4 warnings**（耗时 380.80 秒）。固定端口绕过了
`pytest-postgresql`/`port_for` 在当前 macOS 沙箱中无法选择临时端口的问题；本次剩余失败集中在
MCP 私有地址测试夹具、BYOM 测试环境将 `api.mistral.ai` 解析为保留地址，以及 GraphRAG 测试缺少
`scipy`/触发回退路径。OpenScout intelligence 测试和字体嵌入测试通过。`ruff check .` 通过；
`frontend` 的 lint 和生产构建均以退出码 0 完成，lint 有 320 条既有 warning，构建提示 Node 20.15
低于 Vite 推荐的 20.19+ 以及既有大 chunk warning。这些是当前测试/工具环境与既有测试阻断，不属于
OpenScout Stage A 实现缺陷；在完整依赖、可用网络解析和匹配的 Node 版本环境中复测前，不将该结果
表述为全仓库通过，也不据此改变产品规格。

## 产品范围限制

Stage A 固定为三个仓库和一个时间窗口，仍缺少 Stage B 计划中的任意仓库接入、增量
同步调度、分享权限、反馈闭环和真实用户研究。未知比较单元格会显示“尚未确认”，
不会被推断成“没有该功能”。GraphRAG、重排器和外部模型均可能回退；回退原因必须
在响应追踪中披露。

## PDF 字体部署限制

PDF 渲染器优先读取 `OPENSCOUT_CJK_FONT`，其次使用仓库内的
`docsgpt/intelligence/resources/fonts/NotoSansCJKsc-Regular.ttf`，再查找运行环境字体，
最后才使用 ReportLab 的 `STSong-Light` 回退。仓库内的字体是 Noto Sans CJK SC 的
Regular 400 静态 TTF 实例，依据官方 [Noto CJK Variable TTF](https://github.com/googlefonts/noto-cjk/raw/main/Sans/Variable/TTF/NotoSansCJKsc-VF.ttf)
生成，采用 [SIL Open Font License 1.1](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)，
许可证副本保存在同一资源目录。其 SHA-256 为
`501666bfeb4b1bc8dc1298b8f7d1d36f2a3eddc61feb7b16a77ed62e5840a036`。
报告服务回归测试会检查 PDF 含嵌入式 TrueType 字体且没有使用 `STSong-Light`；自定义部署
仍可通过 `OPENSCOUT_CJK_FONT` 覆盖。不得把 macOS 系统字体直接复制进仓库，也不得将
未验证的字体写成已完成的发布证据。

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
