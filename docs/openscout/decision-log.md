# OpenScout AI 决策记录

## 2026-09-14：将公开 GitHub 活动视为产品信号

公开 GitHub 社区活动属于产品信号，不等同于商业需求。Issue、评论和 Release
反映的是公开社区中的讨论与发布行为，不能单独证明付费意愿、市场规模或商业优先级。

## 2026-09-16：Stage A 保留为实验性作品集证据

使用冻结快照 `stage-a-2026-09-14` 和 20 条 holdout 题运行 routed 配置。事实题
正确率为 0.900，比较/综合问题成功率为 0.890，非 GraphRAG 平均延迟为 0ms，
五个演示场景均通过证据契约；引用精确率为 0.567，未达到 0.900 的发布门槛。
因此不把 OpenScout 标记为 Stage A 全部达标，也不在 README 或简历中隐藏失败案例。

本次数据来自提交的 deterministic lexical proxy；0ms 延迟和 token 数不能外推到
生产模型或网络服务。GitHub 抽样只覆盖三个仓库，并受每仓库 1,000 条 Issue、每条
20 条评论上限影响。五张真实 UI 截图已保存到 `evidence/`，连续短视频仍需维护者在目标
环境录制；完整清单和外部阻塞记录在 [`limitations.md`](limitations.md)。

## 2026-09-17：报告 PDF 随仓库分发 CJK 字体

报告服务使用采用 SIL Open Font License 1.1 的 Noto Sans CJK SC Regular 400 TTF
静态实例，放在 `docsgpt/intelligence/resources/fonts/`，并保留许可证副本。由于
ReportLab 的 `TTFont` 不支持 CFF/PostScript OTF，不能直接使用 Noto CJK OTF；静态
TTF 通过官方 Variable TTF 固定为 Regular 400 后嵌入 PDF。回归测试验证 PDF 包含
TrueType 字体资源且不落到 `STSong-Light` 回退。
