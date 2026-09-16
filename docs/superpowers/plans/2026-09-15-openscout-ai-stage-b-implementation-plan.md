# OpenScout AI 阶段 B 实施计划

> **供智能执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤均使用复选框（`- [ ]`）跟踪状态。

**目标：** 将通过验证的阶段 A 作品集版本扩展为可推广产品，支持任意公开 GitHub 仓库、增量同步、安全的只读报告分享，并记录真实用户任务证据。

**架构：** 复用阶段 A 的项目、记录、索引、查询和报告契约。在创建项目前增加仓库预检边界，并补充持久化的对象级同步游标、删除审计、现有 Celery/RedBeat 调度，以及不会暴露所有者或内部追踪信息的公开报告投影。用户研究资料不写入运行时业务表，只汇总获得同意且已经匿名化的观察结果。

**技术栈：** 阶段 A 技术栈，加上 Celery RedBeat、密码学安全的随机分享令牌、pytest/Vitest 和 Markdown 用户研究记录。

**规格：** `docs/superpowers/specs/2026-09-14-openscout-ai-design.md`

## 全局约束

- 只有在阶段 A 验收测试和实测评估结果均已存在后，才能开始阶段 B。
- 只接受公开 GitHub 仓库；私有仓库支持和扩大 OAuth 权限范围不在本阶段范围内。
- `content_hash` 未变化的记录不得重新索引。
- 外部对象首次缺失后仍保持活跃；只有连续两次成功同步均确认缺失，才能移出活跃索引。
- 部分成功的同步必须提交成功批次，并暴露可重试失败项。
- 公开报告响应不得暴露 `user_id`、GitHub token、服务商凭据、私有存储路径或内部检索追踪。
- 分享链接只读、不可猜测且可以撤销。
- 招募 5—10 名目标用户；只报告实测任务结果和限制，不虚构需求。

---

### 任务 1：预检并创建任意公开仓库项目

**文件：**
- 新建： `docsgpt/intelligence/preflight.py`
- 修改： `docsgpt/intelligence/github_client.py`
- 修改： `docsgpt/api/user/intelligence/routes.py`
- 新建： `tests/intelligence/test_preflight.py`
- 修改： `tests/api/user/intelligence/test_routes.py`
- 新建： `frontend/src/intelligence/RepositorySetup.tsx`
- 新建： `frontend/src/intelligence/RepositorySetup.test.tsx`
- 修改： `frontend/src/intelligence/intelligenceService.ts`
- 修改： `frontend/src/App.tsx`

**接口：**
- 输入：`GitHubLoader.normalize_repo(repo_url: str) -> str`、阶段 A 项目仓储，以及需要认证的 `/api/intelligence` 命名空间。
- 输出：`RepositoryPreflight(repository, default_branch, archived, estimated_counts, warnings)`、`POST /api/intelligence/preflight`，以及从配置到同步的界面流程。

- [x] **步骤 1：编写预检分类测试**

```python
@pytest.mark.parametrize("status,private,expected", [
    (404, False, "not_found"), (200, True, "private_not_supported"),
    (200, False, None),
])
def test_preflight_classifies_repository(status, private, expected, github) -> None:
    github.repository_metadata.return_value = {"status": status, "private": private, "archived": False}
    result = RepositoryPreflightService(github).check("https://github.com/o/r")
    assert result.error_code == expected
```

- [x] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_preflight.py tests/api/user/intelligence/test_routes.py -q`

预期：FAIL，提示缺少预检服务或路由。

- [x] **步骤 3：实现有边界的元数据预检**

将输入规范化为 `owner/name`；在不下载正文的情况下获取仓库元数据和数量估算；拒绝格式错误、非 GitHub 或私有仓库；对已归档、空仓库或超过上限的仓库返回警告。警告不得绕过阶段 A 的数据上限。

- [x] **步骤 4：实现配置界面和创建交接流程**

表单收集 URL 和时间窗口，展示规范化仓库名、Issues/Releases/文档估算数量和上限警告，然后调用现有创建与同步接口。存在错误时禁用创建；对于已归档或达到上限的仓库，必须由用户明确确认。

- [x] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_preflight.py tests/api/user/intelligence/test_routes.py -q`

运行：`cd frontend && npm test -- --run src/intelligence/RepositorySetup.test.tsx`

预期：有效公开仓库可以创建项目；无效或私有仓库不能创建。

```bash
git add docsgpt/intelligence/preflight.py docsgpt/intelligence/github_client.py docsgpt/api/user/intelligence/routes.py tests frontend/src/intelligence frontend/src/App.tsx
git commit -m "feat(openscout): preflight public GitHub repositories"
```

### 任务 2：增量同步并审计删除候选对象

**文件：**
- 新建： `docsgpt/alembic/versions/0033_openscout_incremental_sync.py`
- 修改： `docsgpt/storage/db/models.py`
- 修改： `docsgpt/storage/db/repositories/intelligence.py`
- 修改： `docsgpt/intelligence/sync_service.py`
- 修改： `docsgpt/intelligence/indexing.py`
- 新建： `tests/intelligence/test_incremental_sync.py`
- 修改： `tests/storage/db/repositories/test_intelligence.py`

**接口：**
- 输入：最近成功同步游标、外部对象的 `updated_at`、`content_hash`，以及阶段 A 的定向切片删除能力。
- 输出：`SyncCursor(last_success_at: datetime, external_updated_at: datetime | None)`、`mark_seen(record_id: str, sync_id: str) -> None`、`record_missing(project_id: str, source_type: SourceType, seen_ids: set[str]) -> int`、`deactivate_confirmed_missing(project_id: str) -> list[str]` 和 `IncrementalSyncSummary`。

- [ ] **步骤 1：编写变化、未变化和连续两次缺失测试**

```python
def test_unchanged_record_is_not_reindexed(service, indexer) -> None:
    service.run_incremental(PROJECT_ID, "u1")
    indexer.replace_records.assert_not_called()


def test_record_deactivates_only_after_two_complete_misses(service, repo) -> None:
    service.run_incremental(PROJECT_ID, "u1")
    assert repo.get_record(RECORD_ID)["active"] is True
    service.run_incremental(PROJECT_ID, "u1")
    assert repo.get_record(RECORD_ID)["active"] is False
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_incremental_sync.py tests/storage/db/repositories/test_intelligence.py -q`

预期：FAIL，因为同步游标和删除审计字段尚不存在。

- [ ] **步骤 3：增加数据库迁移和仓储状态转换**

增加 `last_seen_sync_id`、`missing_confirmations integer NOT NULL DEFAULT 0`、`active boolean NOT NULL DEFAULT true` 和 `deactivated_at`。再次发现对象时清零缺失次数；只有某一来源类型完整同步成功后才累计缺失；部分成功或失败的批次不得确认对象缺失。

- [ ] **步骤 4：实现增量采集和定向索引**

使用最近成功同步时间作为 `since`，比较哈希，只索引新增或变化记录；只有记录从活跃转为非活跃时才删除切片。停用后仍保留标准化记录和审计字段。

- [ ] **步骤 5：执行迁移、验证并提交**

运行：`python -m alembic -c docsgpt/alembic.ini upgrade head`

运行：`python -m pytest tests/intelligence/test_incremental_sync.py tests/storage/db/repositories/test_intelligence.py -q`

预期：PASS；重复同步未变化数据时生成 0 个 Embedding，部分失败不会停用任何记录。

```bash
git add docsgpt/alembic/versions/0033_openscout_incremental_sync.py docsgpt/storage/db docsgpt/intelligence tests
git commit -m "feat(openscout): add audited incremental synchronization"
```

### 任务 3：调度同步并展示持久化运行状态

**文件：**
- 修改： `docsgpt/intelligence/tasks.py`
- 修改： `docsgpt/api/user/intelligence/routes.py`
- 修改： `docsgpt/api/user/scheduler_dispatcher.py`
- 新建： `tests/intelligence/test_sync_schedule.py`
- 修改： `frontend/src/intelligence/Overview.tsx`
- 新建： `frontend/src/intelligence/SyncStatus.tsx`
- 新建： `frontend/src/intelligence/SyncStatus.test.tsx`

**接口：**
- 输入：现有 Celery/RedBeat 调度能力和 `sync_intelligence_project`。
- 输出：手动/每日调度契约、幂等分发键 `openscout-sync:{project_id}:{scheduled_at}`，以及带重试操作的可见运行状态。

- [ ] **步骤 1：编写调度与状态测试**

```python
def test_daily_dispatch_uses_project_scoped_idempotency_key(dispatcher) -> None:
    dispatcher.dispatch(PROJECT_ID, scheduled_at=WHEN)
    dispatched = sync_intelligence_project.apply_async.call_args.kwargs["kwargs"]
    assert dispatched["idempotency_key"] == f"openscout-sync:{PROJECT_ID}:{WHEN.isoformat()}"
```

```tsx
it('shows partial counts and a retry action', () => {
  render(<SyncStatus run={partialRun} />);
  expect(screen.getByText('部分完成')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: '重试失败项'})).toBeEnabled();
});
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_sync_schedule.py -q`

运行：`cd frontend && npm test -- --run src/intelligence/SyncStatus.test.tsx`

预期：两组测试均失败，因为调度和状态组件尚不存在。

- [ ] **步骤 3：复用 RedBeat，不引入第二套调度器**

将项目每日同步计划映射到现有调度分发器，分发现有同步任务，并保留有界重试。手动接口使用同一任务和按请求生成的幂等键。

- [ ] **步骤 4：展示透明的同步状态**

展示排队中、运行中、完成、部分完成和失败状态，以及按来源类型统计的对象数、实际覆盖范围、上限标记、最近成功时间、错误类别和重试操作。不得显示原始异常字符串或 token。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_sync_schedule.py tests/api/user/intelligence/test_routes.py -q`

运行：`cd frontend && npm test -- --run src/intelligence/SyncStatus.test.tsx && npm run build`

预期：每个到期时间槽只分发一次任务，界面能展示所有终态。

```bash
git add docsgpt/intelligence/tasks.py docsgpt/api/user docsgpt/api/user/scheduler_dispatcher.py tests frontend/src/intelligence
git commit -m "feat(openscout): schedule and explain intelligence syncs"
```

### 任务 4：分享和撤销经过脱敏的只读报告

**文件：**
- 新建： `docsgpt/alembic/versions/0034_openscout_report_sharing.py`
- 修改： `docsgpt/storage/db/models.py`
- 修改： `docsgpt/storage/db/repositories/intelligence.py`
- 修改： `docsgpt/api/user/intelligence/routes.py`
- 新建： `docsgpt/api/public/__init__.py`
- 新建： `docsgpt/api/public/intelligence.py`
- 修改： `docsgpt/app.py`
- 新建： `tests/api/user/intelligence/test_report_sharing.py`
- 新建： `frontend/src/intelligence/SharedReportView.tsx`
- 新建： `frontend/src/intelligence/SharedReportView.test.tsx`
- 修改： `frontend/src/App.tsx`

**接口：**
- 输入：阶段 A 报告 JSON。
- 输出：需要认证的 `POST /api/intelligence/reports/<id>/share` 和 `DELETE /api/intelligence/reports/<id>/share`、无需认证的 Flask 蓝图路由 `GET /api/public/intelligence/reports/<token>`，以及前端路由 `/reports/shared/:token`。

- [ ] **步骤 1：编写所有权、撤销和脱敏测试**

```python
def test_public_report_projection_redacts_internal_fields(client, shared_report) -> None:
    response = client.get(f"/api/public/intelligence/reports/{shared_report.token}")
    payload = response.get_json()
    assert response.status_code == 200
    assert "user_id" not in json.dumps(payload)
    assert "trace" not in json.dumps(payload)


def test_revoked_token_returns_not_found(client, revoked_token) -> None:
    assert client.get(f"/api/public/intelligence/reports/{revoked_token}").status_code == 404
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/api/user/intelligence/test_report_sharing.py -q`

预期：FAIL，提示缺少接口或数据库字段。

- [ ] **步骤 3：增加哈希令牌和公开数据投影**

使用 `secrets.token_urlsafe(32)` 生成 32 个随机字节，只存储 SHA-256 令牌哈希以及 `shared_at`/`revoked_at`；仅在创建分享时返回一次明文令牌。在 `docsgpt/app.py` 注册独立的公开 Flask 蓝图，不得削弱需要认证的用户命名空间。公开序列化只允许报告标题、章节、来源 URL、覆盖范围和生成时间。

- [ ] **步骤 4：实现公开界面和所有者控制**

所有者可以创建、复制和撤销链接。公开路由无需认证，只提供只读报告和来源链接；不得暴露编辑、重新同步、下载私有产物或查看内部追踪的操作。

- [ ] **步骤 5：验证并提交**

运行：`python -m alembic -c docsgpt/alembic.ini upgrade head`

运行：`python -m pytest tests/api/user/intelligence/test_report_sharing.py -q`

运行：`cd frontend && npm test -- --run src/intelligence/SharedReportView.test.tsx && npm run build`

预期：所有者隔离、令牌熵、撤销和脱敏测试全部 PASS。

```bash
git add docsgpt/alembic/versions/0034_openscout_report_sharing.py docsgpt/storage/db docsgpt/api/user/intelligence docsgpt/api/public docsgpt/app.py tests frontend/src
git commit -m "feat(openscout): share sanitized read-only reports"
```

### 任务 5：通过真实用户任务验证推广价值

**文件：**
- 新建： `research/stage-b/research-protocol.md`
- 新建： `research/stage-b/task-script.md`
- 新建： `research/stage-b/observations.csv`
- 新建： `research/stage-b/findings.md`
- 新建： `research/stage-b/consent-and-redaction.md`
- 修改： `README-openscout.md`
- 修改： `docs/openscout/decision-log.md`

**接口：**
- 输入：已部署的阶段 B 版本和一项统一的竞品研究任务。
- 输出：5—10 名参与者的匿名观察记录、任务完成率、完成时间中位数、证据点击率、报告使用意愿、失败问题排序，以及有证据支持的继续/迭代/停止决策。

- [ ] **步骤 1：在招募前写定研究协议**

协议必须定义目标角色、一项 15 分钟研究任务、成功标准、中立主持话术、知情同意、不收集 GitHub 凭据，以及规格中的五项指标。参与者编号使用 `P01`—`P10`，姓名和邮箱不得进入仓库。

- [ ] **步骤 2：进行一次试运行，之后不再修改成功标准**

邀请一名试运行参与者执行任务。只修正容易误解的说明或损坏的产品行为；正式测试前必须记录每次协议变更的日期和原因。

- [ ] **步骤 3：进行 5—10 场测试，每名参与者记录一行**

`observations.csv` 的列必须严格为：

```csv
participant_id,role,completed,seconds,evidence_clicks,report_exported,would_reuse,blocking_failure,notes_redacted
```

不得引导参与者得到答案，也不得替换失败场次。

- [ ] **步骤 4：分析结果并进行一次有边界的迭代**

计算完成率、用时中位数、平均证据点击数、导出率和再次使用意愿。按受影响参与者数量排列阻塞性问题；只修复影响核心任务的前三项问题，重新运行对应自动化回归测试，并记录延后反馈。

- [ ] **步骤 5：发布真实研究结论并创建版本标签**

运行：`ruff check .`

运行：`KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`

运行：`cd frontend && npm run lint && npm run build`

预期：自动化验证成功；`findings.md` 包含样本量、方法、原始聚合值、限制和决策；README 和简历只使用这些实测结果。

```bash
git add research/stage-b README-openscout.md docs/openscout/decision-log.md
git commit -m "docs(openscout): publish stage B user validation"
git tag openscout-stage-b
```

## 阶段 B 自检记录

- 规格覆盖：任意公开仓库配置、增量同步、状态/失败、每日调度、安全报告分享、撤销和 5—10 名用户任务验证，均对应一个可独立测试的任务。
- 安全覆盖：公开响应明确排除私有仓库访问、明文令牌存储、所有者字段、凭据、存储路径和内部追踪。
- 类型一致性：阶段 B 扩展阶段 A 的 `IntelligenceProject`、`SyncSummary` 和 `ReportDocument`，不创建平行数据结构。
- 范围边界：支付、企业多租户、社交/新闻来源、路线图自动决策和复杂权限仍属于非目标。
