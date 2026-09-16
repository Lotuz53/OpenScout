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
20 条评论上限影响。截图和短视频不在仓库中伪造，捕获位置与 PR 清单记录在
[`limitations.md`](limitations.md)。
