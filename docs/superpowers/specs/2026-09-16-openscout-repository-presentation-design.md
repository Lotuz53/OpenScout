# OpenScout Repository Presentation Design

**Date:** 2026-09-16  
**Status:** Approved

## Goal

让 `Lotuz53/OpenScout` 在 GitHub 上以完整、独立的 OpenScout AI 项目呈现，同时保留 DocsGPT 的历史提交以保证来源可追溯。

## Decisions

1. 将 OpenScout 项目说明放入根目录 `README.md`，并删除重复的 `README-openscout.md`。
2. 将根目录 `CONTRIBUTING.md` 改为 OpenScout 的贡献指南；仅在说明基础能力来源时保留 DocsGPT 链接。
3. 从当前 Stage A 提交创建 `main` 分支，将其推送到 OpenScout 仓库并设为 GitHub 默认分支。
4. 保留 `feature/openscout-design` 作为当前开发分支，不删除任何分支。
5. 保留现有 DocsGPT 提交祖先，不执行历史重写或孤立分支迁移。
6. 将本地 Git 远程整理为 `origin=https://github.com/Lotuz53/OpenScout.git` 和 `upstream=https://github.com/arc53/DocsGPT.git`，便于后续同步与推送。

## Scope and non-goals

本次只处理仓库入口文档、贡献说明、默认分支和本地远程配置。不会修改 OpenScout 功能代码、评估结果、Stage A/B 计划，也不会清理 DocsGPT 的历史提交或强制覆盖已有远程分支。

## Validation

- 检查根目录 README 标题、项目链接和关键内部链接。
- 运行 `git diff --check`。
- 确认 `main` 和 `feature/openscout-design` 指向同一个 Stage A 提交。
- 通过 GitHub 公开接口确认 `main` 为默认分支，并确认远端分支哈希与本地一致。
- 确认用户已有的未提交 `AGENTS.md` 修改仍未纳入提交。
