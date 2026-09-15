# OpenScout AI 阶段 A 实施计划

> **供智能执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤均使用复选框（`- [ ]`）跟踪状态。

**目标：** 构建可用于简历作品集的 OpenScout AI：采集固定的 Dify、RAGFlow 和 FastGPT GitHub 数据集，使用可追溯证据回答五类问题，完成产品对比与报告导出，并发布可复现的 RAG 实验。

**架构：** 在 DocsGPT 上增加边界清晰的 `docsgpt/intelligence/` 垂直功能。PostgreSQL 保存标准化 GitHub 事实和确定性统计；pgvector/HybridRetriever 保存并检索切片；现有 GraphRAG 只处理经过筛选的关系型问题；React 功能目录消费统一的强类型 `/api/intelligence` 契约。GitHub 采集、标准化、持久化、索引、路由、证据校验和展示保持为独立单元。

**技术栈：** Python 3.12、Flask-RESTX、SQLAlchemy Core、Alembic、PostgreSQL/pgvector、Redis/Celery、Pydantic 2、pytest、React 18、TypeScript、Redux Toolkit、Vite/Vitest、ReportLab。

**规格：** `docs/superpowers/specs/2026-09-14-openscout-ai-design.md`

## 全局约束

- 阶段 A 仓库只能是 `langgenius/dify`、`infiniflow/ragflow` 和 `labring/FastGPT`。
- 初始数据窗口严格为 `2025-09-14` 至 `2026-09-14`；后续运行按滚动 12 个月处理。
- 每个仓库最多保留 1,000 条非 PR Issue；每条 Issue 最多保留按创建时间排序的前 20 条评论。
- 范围只包括根目录 README、`docs/` 下的文本文件、Releases、Issues 和 Issue 评论。
- 幂等键为 `repository + source_type + external_id`；`content_hash` 未变化的记录不得重新生成 Embedding。
- GraphRAG 接收文档、Releases 和每个仓库最多 300 条高信号 Issues；不得提供数量或趋势统计。
- 路由器置信度低于 `0.65` 时回退到 Hybrid 检索。
- 界面显式过滤条件优先于从问题文本推断出的过滤条件。
- 每条事实性结论至少关联一个证据 id；没有支持的内容只能标记为 `inference` 或拒绝回答。
- 精确统计由 PostgreSQL 完成；LLM 不得执行精确计数。
- 后端新增代码必须使用类型标注和 Google 风格 docstring，单行不超过 120 个字符。
- 前端新增代码放在 `frontend/src/intelligence/`，共享状态使用 Redux，不对 DocsGPT 界面进行大范围重构。
- 指标和简历表述只能使用实测值；不得提交密钥、GitHub token 或原始用户身份信息。

## 文件结构

| 区域 | 文件 | 职责 |
|---|---|---|
| 领域契约 | `docsgpt/intelligence/schemas.py` | 服务共享的枚举和不可变请求/结果模型 |
| GitHub 边界 | `docsgpt/intelligence/github_client.py` | HTTP、分页、限流分类和原始对象 |
| 标准化 | `docsgpt/intelligence/normalizer.py` | 过滤、内容模板、元数据和稳定哈希 |
| 持久化 | `docsgpt/storage/db/repositories/intelligence.py` | 按所有者隔离的项目、记录、同步任务、报告和统计 |
| 编排 | `docsgpt/intelligence/sync_service.py`、`tasks.py` | 部分成功采集、持久化、索引和任务状态 |
| 检索 | `indexing.py`、`filters.py`、`reranker.py`、`query_router.py`、`query_service.py` | 切片、检索、路由、回退和追踪 |
| 可信层 | `analytics.py`、`confidence.py`、`claims.py` | SQL 统计、确定性可信度和引用强制校验 |
| 报告 | `report_service.py` | 将同一报告模型渲染为 Markdown 和 PDF |
| API | `docsgpt/api/user/intelligence/routes.py` | 只提供需要认证的 JSON 接口，不包含 SQL 或服务商逻辑 |
| 前端 | `frontend/src/intelligence/` | 首页、工作台、证据、矩阵和报告体验 |
| 评估 | `evaluation/` | 带版本的问题、配置、运行记录、指标和摘要 |

---

### 任务 1：冻结阶段 A 契约和基线

**文件：**
- 新建： `docsgpt/intelligence/__init__.py`
- 新建： `docsgpt/intelligence/schemas.py`
- 新建： `tests/intelligence/test_schemas.py`
- 新建： `evaluation/fixtures/stage_a_snapshot.json`
- 新建： `docs/openscout/decision-log.md`

**接口：**
- 输入：Pydantic 2 和 ISO-8601 UTC 时间。
- 输出：`SourceType`、`QueryIntent`、`RetrievalStrategy`、`ClaimKind`、`Confidence`、`IntelligenceProject`、`IntelligenceRecord`、`QueryFilters`、`QueryRequest`、`Evidence`、`Claim`、`Coverage`、`SyncSummary`、`RetrievalTrace` 和 `QueryResult`。

- [x] **步骤 1：编写数据模型契约测试**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from docsgpt.intelligence.schemas import Claim, ClaimKind, Evidence


def test_factual_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        Claim(id="c1", text="Dify released feature X", kind=ClaimKind.FACT, evidence_ids=[])


def test_evidence_serializes_utc_timestamp() -> None:
    evidence = Evidence(
        id="e1", record_id="r1", repository="langgenius/dify",
        source_type="release", title="v1", excerpt="notes", source_url="https://github.com/x",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evidence.model_dump(mode="json")["occurred_at"] == "2026-01-01T00:00:00Z"
```

- [x] **步骤 2：运行契约测试并确认导入失败**

运行：`python -m pytest tests/intelligence/test_schemas.py -q`

预期：FAIL，并出现 `ModuleNotFoundError: No module named 'docsgpt.intelligence'`。

- [x] **步骤 3：实现共享枚举和数据模型**

```python
class SourceType(StrEnum):
    DOCUMENTATION = "documentation"
    ISSUE = "issue"
    ISSUE_COMMENT = "issue_comment"
    RELEASE = "release"


class QueryIntent(StrEnum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    AGGREGATE = "aggregate"
    RELATIONAL = "relational"


class RetrievalStrategy(StrEnum):
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    SQL_PLUS_HYBRID = "sql_plus_hybrid"
    SPLIT_HYBRID = "split_hybrid"
    GRAPHRAG = "graphrag"


class ClaimKind(StrEnum):
    FACT = "fact"
    STATISTIC = "statistic"
    INFERENCE = "inference"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntelligenceProject(BaseModel):
    id: str
    user_id: str
    repository: str
    window_start: date
    window_end: date
    status: Literal["draft", "syncing", "ready", "partial", "failed"]
    last_synced_at: datetime | None = None


class IntelligenceRecord(BaseModel):
    id: str | None = None
    repository: str
    source_type: SourceType
    external_id: str
    title: str
    body: str
    source_url: HttpUrl
    state: str | None = None
    labels: list[str] = Field(default_factory=list)
    comments_count: int = 0
    reactions_count: int = 0
    version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_hash: str

    def to_repository_params(self, project_id: str) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["project_id"] = project_id
        data["metadata"] = json.dumps({
            key: data[key] for key in (
                "state", "labels", "comments_count", "reactions_count", "version",
                "created_at", "updated_at", "published_at",
            )
        })
        return data


class SyncFailure(BaseModel):
    source_type: SourceType
    category: Literal["rate_limit", "auth", "not_found", "network", "invalid_payload"]
    retryable: bool
    message: str


class QueryFilters(BaseModel):
    repositories: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    filters: QueryFilters = Field(default_factory=QueryFilters)


class Evidence(BaseModel):
    id: str
    record_id: str
    repository: str
    source_type: SourceType
    title: str
    excerpt: str
    source_url: HttpUrl
    occurred_at: datetime | None = None
    author: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    kind: ClaimKind
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW

    @model_validator(mode="after")
    def require_evidence_for_facts(self) -> "Claim":
        if self.kind in {ClaimKind.FACT, ClaimKind.STATISTIC} and not self.evidence_ids:
            raise ValueError("evidence_ids required for factual claims")
        return self


class Coverage(BaseModel):
    repositories: list[str]
    date_from: date | None
    date_to: date | None
    counts: dict[SourceType, int]
    capped: bool = False
    last_synced_at: datetime | None = None


class SyncSummary(BaseModel):
    status: Literal["complete", "partial", "failed"]
    counts: dict[SourceType, int]
    failures: list[SyncFailure] = Field(default_factory=list)
    coverage: Coverage


class RetrievalTrace(BaseModel):
    intent: QueryIntent
    strategy: RetrievalStrategy
    fallback_reason: str | None = None
    applied_filters: QueryFilters


class QueryResult(BaseModel):
    answer: str
    claims: list[Claim]
    evidence: list[Evidence]
    coverage: Coverage
    latency_ms: int
    trace: RetrievalTrace
```

后续 API 和界面类型必须严格复用这些序列化字段名。

- [x] **步骤 4：增加脱敏的数据快照清单和第一条决策记录**

```json
{
  "snapshot_id": "stage-a-2026-09-14",
  "window": {"from": "2025-09-14", "to": "2026-09-14"},
  "repositories": ["langgenius/dify", "infiniflow/ragflow", "labring/FastGPT"],
  "issue_limit_per_repository": 1000,
  "comment_limit_per_issue": 20
}
```

在 `decision-log.md` 中记录：公开 GitHub 社区活动属于产品信号，不等同于商业需求。

- [x] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_schemas.py -q`

预期：PASS。

```bash
git add docsgpt/intelligence tests/intelligence evaluation/fixtures docs/openscout/decision-log.md
git commit -m "feat(openscout): define stage A intelligence contracts"
```

### 任务 2：持久化项目、记录、同步运行和报告

**文件：**
- 新建： `docsgpt/alembic/versions/0032_openscout_intelligence.py`
- 修改： `docsgpt/storage/db/models.py`
- 新建： `docsgpt/storage/db/repositories/intelligence.py`
- 新建： `tests/storage/db/repositories/test_intelligence.py`

**接口：**
- 输入：任务 1 的 `IntelligenceRecord` 和 SQLAlchemy `Connection`。
- 输出：`IntelligenceRepository.create_project(user_id: str, repository: str, window_start: date, window_end: date) -> dict`、`upsert_record(project_id: str, record: IntelligenceRecord) -> UpsertOutcome`、`start_sync_run(project_id: str) -> dict`、`finish_sync_run(run_id: str, summary: SyncSummary) -> dict` 和 `save_report(user_id: str, report_data: dict[str, Any]) -> dict`。

- [x] **步骤 1：编写所有权和哈希幂等仓储测试**

```python
def test_upsert_record_skips_unchanged_content(pg_conn, intelligence_record) -> None:
    repo = IntelligenceRepository(pg_conn)
    first = repo.upsert_record("project-uuid", intelligence_record)
    second = repo.upsert_record("project-uuid", intelligence_record)
    assert first.changed is True
    assert second.changed is False
    assert second.record_id == first.record_id


def test_project_lookup_is_owner_scoped(pg_conn) -> None:
    row = IntelligenceRepository(pg_conn).create_project(
        user_id="owner", repository="langgenius/dify",
        window_start=date(2025, 9, 14), window_end=date(2026, 9, 14),
    )
    assert IntelligenceRepository(pg_conn).get_project(str(row["id"]), "other") is None
```

- [x] **步骤 2：运行仓储测试并确认缺少数据表或类**

运行：`python -m pytest tests/storage/db/repositories/test_intelligence.py -q`

预期：FAIL，因为 `IntelligenceRepository` 和相关数据表尚不存在。

- [x] **步骤 3：增加数据库迁移和匹配的 SQLAlchemy Core 表定义**

创建 `intelligence_projects`、`intelligence_records`、`intelligence_sync_runs`、`intelligence_reports` 和 `intelligence_topic_runs`。主题表保存 `project_id`、`snapshot_id`、`algorithm_version`、`clusters` JSONB 和 `created_at`，确保趋势结果可复现。强制执行：

```sql
UNIQUE (project_id, source_type, external_id);
CHECK (source_type IN ('documentation', 'issue', 'issue_comment', 'release'));
CREATE INDEX intelligence_records_project_type_idx ON intelligence_records(project_id, source_type);
CREATE INDEX intelligence_records_created_idx ON intelligence_records(project_id, created_at);
CREATE INDEX intelligence_records_labels_gin_idx ON intelligence_records USING gin(labels);
```

`intelligence_reports` 直接拥有自身 JSON 和渲染文件路径；不得复用 `artifacts`，因为 `artifacts_parent_present_check` 强制要求会话或工作流父对象。

- [x] **步骤 4：使用单个按所有者隔离的类实现仓储**

```python
@dataclass(frozen=True)
class UpsertOutcome:
    record_id: str
    changed: bool


class IntelligenceRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert_record(self, project_id: str, record: IntelligenceRecord) -> UpsertOutcome:
        row = self._conn.execute(
            text("""
                WITH changed AS (
                    INSERT INTO intelligence_records
                        (project_id, repository, source_type, external_id, title, body,
                         source_url, metadata, content_hash, retrieved_at)
                    VALUES
                        (CAST(:project_id AS uuid), :repository, :source_type, :external_id,
                         :title, :body, :source_url, CAST(:metadata AS jsonb), :content_hash,
                         :retrieved_at)
                    ON CONFLICT (project_id, source_type, external_id) DO UPDATE SET
                        title = EXCLUDED.title, body = EXCLUDED.body,
                        source_url = EXCLUDED.source_url, metadata = EXCLUDED.metadata,
                        content_hash = EXCLUDED.content_hash,
                        retrieved_at = EXCLUDED.retrieved_at, updated_at = now()
                    WHERE intelligence_records.content_hash <> EXCLUDED.content_hash
                    RETURNING id
                )
                SELECT id, true AS changed FROM changed
                UNION ALL
                SELECT id, false AS changed FROM intelligence_records
                WHERE project_id = CAST(:project_id AS uuid)
                  AND source_type = :source_type AND external_id = :external_id
                LIMIT 1
            """),
            record.to_repository_params(project_id),
        ).mappings().one()
        return UpsertOutcome(record_id=str(row["id"]), changed=bool(row["changed"]))
```

所有值都使用绑定参数，并通过 `row_to_dict` 返回字典；只有统计排序和维度名允许使用白名单。

- [x] **步骤 5：执行迁移、降级、重新迁移、测试并提交**

运行：`python -m alembic -c docsgpt/alembic.ini upgrade head`

运行：`python -m alembic -c docsgpt/alembic.ini downgrade 0031_token_usage_cache_tokens`

运行：`python -m alembic -c docsgpt/alembic.ini upgrade head`

运行：`python -m pytest tests/storage/db/repositories/test_intelligence.py -q`

预期：所有命令成功，测试 PASS。

```bash
git add docsgpt/alembic/versions/0032_openscout_intelligence.py docsgpt/storage/db/models.py docsgpt/storage/db/repositories/intelligence.py tests/storage/db/repositories/test_intelligence.py
git commit -m "feat(openscout): persist intelligence records and runs"
```

### 任务 3：采集有数量边界的 GitHub Issues、评论和 Releases

**文件：**
- 新建： `docsgpt/intelligence/github_client.py`
- 新建： `tests/intelligence/test_github_client.py`
- 修改： `docsgpt/parser/remote/github_loader.py`

**接口：**
- 输入：`GitHubLoader.normalize_repo(repo_url: str) -> str` 和 `settings.GITHUB_ACCESS_TOKEN`。
- 输出：`GitHubClient.iter_issues(repo, since, until, limit=1000)`、`iter_comments(repo, issue_number, limit=20)`、`iter_releases(repo, since, until)` 和强类型 `GitHubRateLimitError(reset_at)`。

- [ ] **步骤 1：编写固定响应测试**

```python
def test_iter_issues_filters_pull_requests_and_stops_at_limit(responses) -> None:
    responses.add(responses.GET, "https://api.github.com/repos/o/r/issues?state=all&per_page=100&page=1", json=[
        {"id": 1, "number": 1, "title": "issue", "updated_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "number": 2, "title": "pr", "pull_request": {}},
    ], headers={"Link": ""})
    rows = list(GitHubClient().iter_issues("o/r", DATE_FROM, DATE_TO, limit=1))
    assert [row["id"] for row in rows] == [1]


def test_rate_limit_is_recoverable(responses) -> None:
    responses.add(responses.GET, re.compile(r"api.github.com"), status=403,
                  headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000000"})
    with pytest.raises(GitHubRateLimitError) as exc:
        list(GitHubClient().iter_releases("o/r", DATE_FROM, DATE_TO))
    assert exc.value.reset_at.timestamp() == 1800000000
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_github_client.py -q`

预期：FAIL，提示缺少 `docsgpt.intelligence.github_client`。

- [ ] **步骤 3：提取现有鉴权请求接口**

仅在必要时修改 `GitHubLoader._make_request()`，让两个调用方共享请求头、状态分类和超时设置；保持现有加载器行为和测试不变。

- [ ] **步骤 4：实现不阻塞等待的有界分页**

```python
def _iter_pages(self, url: str, params: dict[str, object]) -> Iterator[dict[str, Any]]:
    page = 1
    while True:
        response = self._request(url, params={**params, "per_page": 100, "page": page})
        batch = response.json()
        if not batch:
            return
        yield from batch
        if 'rel="next"' not in response.headers.get("Link", ""):
            return
        page += 1
```

在代码中按请求窗口过滤，按 `created_at` 排序评论并截取前 20 条。遇到限流时抛出异常，由 Celery 决定重试时间。

- [ ] **步骤 5：运行局部测试和现有加载器测试，然后提交**

运行：`python -m pytest tests/intelligence/test_github_client.py tests/parser -q`

预期：PASS。

```bash
git add docsgpt/intelligence/github_client.py docsgpt/parser/remote/github_loader.py tests/intelligence/test_github_client.py
git commit -m "feat(openscout): collect bounded GitHub community data"
```

### 任务 4：将 GitHub 对象标准化为情报记录

**文件：**
- 新建： `docsgpt/intelligence/normalizer.py`
- 新建： `tests/intelligence/test_normalizer.py`
- 新建： `tests/intelligence/fixtures/github_objects.json`

**接口：**
- 输入：原始 GitHub API 字典和 `SourceType`。
- 输出：`is_supported_document(path: str) -> bool`、`normalize_document(repository: str, path: str, body: str, source_url: str, retrieved_at: datetime) -> IntelligenceRecord`、`normalize_issue(repository: str, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord`、`normalize_comment(repository: str, issue_number: int, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord`、`normalize_release(repository: str, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord` 和 `content_hash(body: str, metadata: Mapping[str, Any]) -> str`。

- [ ] **步骤 1：编写过滤和稳定哈希测试**

```python
@pytest.mark.parametrize("path,expected", [
    ("README.md", True), ("docs/guide.md", True),
    ("src/main.py", False), ("documentation.md", False),
])
def test_supported_document_scope(path: str, expected: bool) -> None:
    assert is_supported_document(path) is expected


def test_issue_hash_ignores_retrieval_time(raw_issue) -> None:
    a = normalize_issue("o/r", raw_issue, retrieved_at=UTC_A)
    b = normalize_issue("o/r", raw_issue, retrieved_at=UTC_B)
    assert a.content_hash == b.content_hash
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_normalizer.py -q`

预期：FAIL，提示缺少标准化函数。

- [ ] **步骤 3：实现按来源区分的模板和规范化哈希**

```python
def content_hash(body: str, metadata: Mapping[str, Any]) -> str:
    canonical = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{body.strip()}\n{canonical}".encode()).hexdigest()
```

只对承载内容的字段计算哈希，排除 `retrieved_at`。保留 Markdown 标题、列表和代码块。`source_url` 必须使用 GitHub HTML 地址，不得使用 API 地址。

- [ ] **步骤 4：对 20 条标准化记录执行精确固定数据断言**

增加 `test_normalized_fixture_matches_expected_json()`：读取 `github_objects.json`，标准化全部 20 条记录，并将 `model_dump(mode="json")` 与提交到仓库的预期列表进行比较。

运行：`python -m pytest tests/intelligence/test_normalizer.py::test_normalized_fixture_matches_expected_json -q`

预期：固定快照包含四类来源的仓库、来源类型、日期、标签、数量、版本、URL 和哈希。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_normalizer.py -q`

预期：PASS，并且不会修改快照。

```bash
git add docsgpt/intelligence/normalizer.py tests/intelligence
git commit -m "feat(openscout): normalize traceable GitHub evidence"
```

### 任务 5：编排支持部分成功的同步流程

**文件：**
- 新建： `docsgpt/intelligence/sync_service.py`
- 新建： `docsgpt/intelligence/tasks.py`
- 修改： `docsgpt/celeryconfig.py`
- 新建： `tests/intelligence/test_sync_service.py`
- 新建： `tests/intelligence/test_tasks.py`

**接口：**
- 输入：`GitHubClient`、标准化函数和 `IntelligenceRepository`。
- 输出：`SyncService.run(project_id: str, user_id: str) -> SyncSummary` 和 Celery 任务 `sync_intelligence_project(project_id, user_id, idempotency_key=None) -> dict`。

- [ ] **步骤 1：编写部分成功服务测试**

```python
def test_sync_commits_releases_when_issues_fail(repo, github, indexer) -> None:
    github.iter_releases.return_value = [RAW_RELEASE]
    github.iter_issues.side_effect = GitHubRateLimitError(RESET_AT)
    summary = SyncService(repo, github, indexer).run(PROJECT_ID, "u1")
    assert summary.status == "partial"
    assert summary.counts["release"] == 1
    assert summary.failures[0].source_type == "issue"
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_sync_service.py tests/intelligence/test_tasks.py -q`

预期：FAIL，提示缺少服务和任务。

- [ ] **步骤 3：实现每个来源批次一个事务**

```python
for source_type, collector in collectors.items():
    try:
        records = [normalize(raw) for raw in collector()]
        changed = repository.upsert_records(project_id, records)
        indexer.replace_records(project_id, changed)
        summary.record_success(source_type, records)
    except RecoverableGitHubError as exc:
        summary.record_failure(source_type, exc)
```

持久化状态 `queued -> running -> complete|partial|failed`；记录准确对象数、最早/最晚时间、上限标记、错误类别和最近成功同步时间。

- [ ] **步骤 4：注册具备幂等性和有界重试的 Celery 任务**

```python
@celery.task(bind=True, autoretry_for=(RecoverableGitHubError,), retry_backoff=True,
             retry_kwargs={"max_retries": 4})
@with_idempotency("sync_intelligence_project")
def sync_intelligence_project(self, *, project_id: str, user_id: str,
                              idempotency_key: str | None = None) -> dict:
    return build_sync_service().run(project_id, user_id).model_dump(mode="json")
```

将 `docsgpt.intelligence.tasks` 加入 `celeryconfig.imports`；不得放入解析或 Embedding 队列。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_sync_service.py tests/intelligence/test_tasks.py -q`

预期：PASS；重试会保留已经成功的来源批次。

```bash
git add docsgpt/intelligence/sync_service.py docsgpt/intelligence/tasks.py docsgpt/celeryconfig.py tests/intelligence
git commit -m "feat(openscout): synchronize GitHub data with partial success"
```

### 任务 6：仅索引变化记录并保留可追溯切片元数据

**文件：**
- 新建： `docsgpt/intelligence/indexing.py`
- 新建： `tests/intelligence/test_indexing.py`
- 修改： `docsgpt/intelligence/sync_service.py`

**接口：**
- 输入：变化的 `IntelligenceRecord` 记录，以及 `VectorCreator.create_vectorstore(settings.VECTOR_STORE, source_id=project_id, embeddings_key=settings.EMBEDDINGS_KEY)`。
- 输出：`IntelligenceIndexer.replace_records(project_id: str, records: Sequence[IntelligenceRecord]) -> IndexSummary` 和 `chunks_for_record(record) -> list[Document]`。

- [ ] **步骤 1：编写切片和无变化重建索引测试**

```python
def test_issue_stays_single_chunk_when_under_limit() -> None:
    chunks = chunks_for_record(issue_record(body="short"))
    assert len(chunks) == 1
    assert chunks[0].metadata["record_id"] == "issue:42"


def test_unchanged_sync_adds_no_embeddings(repo, vector_store, record) -> None:
    indexer = IntelligenceIndexer(repo, vector_store)
    assert indexer.replace_records(PROJECT_ID, [record]).embedded_chunks == 1
    assert indexer.replace_records(PROJECT_ID, []).embedded_chunks == 0
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_indexing.py -q`

预期：FAIL，提示缺少索引器。

- [ ] **步骤 3：实现感知来源类型的切片策略**

README/文档按 Markdown 标题边界切分；Issue/Release 在未超过 token 上限时保持为一个切片，超过后使用递归切分。每个切片的元数据字典包含：

```python
{
    "record_id": record.id,
    "project_id": project_id,
    "repository": record.repository,
    "source_type": record.source_type.value,
    "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
    "version": record.version,
    "source": record.source_url,
}
```

- [ ] **步骤 4：实现定向替换**

通过稳定元数据来源 `openscout://{project_id}/{record_id}` 删除旧切片，使用 `add_texts` 增加新切片，并保存返回的切片 id 供 GraphRAG 筛选。单条增量记录变化时不得调用 `delete_index()`。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_indexing.py tests/vectorstore/test_pgvector.py -q`

预期：PASS；修改一条 Issue 只会替换该 Issue 的切片。

```bash
git add docsgpt/intelligence/indexing.py docsgpt/intelligence/sync_service.py tests/intelligence/test_indexing.py
git commit -m "feat(openscout): index changed evidence records"
```

### 任务 7：提供项目、同步、概览和查询契约

**文件：**
- 新建： `docsgpt/api/user/intelligence/__init__.py`
- 新建： `docsgpt/api/user/intelligence/routes.py`
- 修改： `docsgpt/api/user/routes.py`
- 新建： `tests/api/user/intelligence/test_routes.py`
- 新建： `docsgpt/intelligence/query_service.py`
- 新建： `tests/intelligence/test_query_service.py`
- 新建： `docsgpt/seed/intelligence_projects.py`

**接口：**
- 输入：按所有者隔离的仓储、Celery 任务、`HybridRetriever` 和任务 1 的数据模型。
- 输出：`POST /api/intelligence/projects`、`POST /api/intelligence/projects/<id>/sync`、`GET /api/intelligence/projects`、`GET /api/intelligence/projects/<id>`、`GET /api/intelligence/sync-runs/<id>`、`GET /api/intelligence/overview` 和 `POST /api/intelligence/query`。

- [ ] **步骤 1：编写认证、所有权和响应结构 API 测试**

```python
def test_query_requires_auth(client) -> None:
    assert client.post("/api/intelligence/query", json={"question": "x"}).status_code == 401


def test_query_shape(client, auth_headers, mock_query_service) -> None:
    response = client.post("/api/intelligence/query", headers=auth_headers, json={
        "question": "Which product added SSO?",
        "filters": {"repositories": ["langgenius/dify"]},
    })
    assert set(response.json) == {"answer", "claims", "evidence", "coverage", "latency_ms", "trace"}


def test_stage_a_seed_contains_exact_repositories() -> None:
    assert [item.repository for item in stage_a_projects()] == [
        "langgenius/dify", "infiniflow/ragflow", "labring/FastGPT",
    ]
```

- [ ] **步骤 2：运行测试并确认路由失败**

运行：`python -m pytest tests/api/user/intelligence/test_routes.py tests/intelligence/test_query_service.py -q`

预期：FAIL，返回 404 或提示缺少导入。

- [ ] **步骤 3：实现轻量命名空间和请求校验**

设置 `Namespace("intelligence", path="/api")`；读取 `request.decoded_token["sub"]`；在数据库类型转换前拒绝格式错误的 UUID；在 `db_readonly()`/`db_session()` 中调用服务；路由内不得执行 SQL。增加幂等预置函数，用固定窗口创建阶段 A 的三个仓库，重复运行不得产生重复项目。

- [ ] **步骤 4：实现第一版仅使用 Hybrid 的查询链路**

```python
class QueryService:
    def query(self, request: QueryRequest, user_id: str) -> QueryResult:
        evidence = self.retriever.retrieve(request.question, request.filters)
        claims = self.generator.generate(request.question, evidence)
        return enforce_citations(claims=claims, evidence=evidence, coverage=self.coverage(request.filters))
```

本任务中 `trace.strategy` 固定为 `hybrid`；SQL、路由和 GraphRAG 在后续任务实现。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/api/user/intelligence/test_routes.py tests/intelligence/test_query_service.py -q`

预期：PASS，覆盖 401、403/404 所有者隔离、400 参数校验和 202 同步分发。

```bash
git add docsgpt/api/user/intelligence docsgpt/api/user/routes.py docsgpt/intelligence/query_service.py docsgpt/seed/intelligence_projects.py tests/api/user/intelligence tests/intelligence/test_query_service.py
git commit -m "feat(openscout): expose intelligence project and query APIs"
```

### 任务 8：构建可复现评估框架和向量/混合检索实验

**文件：**
- 新建： `evaluation/dataset/questions.dev.jsonl`
- 新建： `evaluation/dataset/questions.holdout.jsonl`
- 新建： `evaluation/configs/vector.yaml`
- 新建： `evaluation/configs/hybrid.yaml`
- 新建： `evaluation/metrics.py`
- 新建： `evaluation/run_eval.py`
- 新建： `evaluation/summarize.py`
- 新建： `evaluation/check_regression.py`
- 新建： `tests/evaluation/test_metrics.py`

**接口：**
- 输入：兼容 `POST /api/intelligence/query` 的查询执行器和固定快照 id。
- 输出：`recall_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float`、`ndcg_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float`、`citation_precision(cited: Sequence[str], expected: Sequence[str]) -> float`、JSONL 运行记录和 Markdown 对比摘要。

- [ ] **步骤 1：使用人工计算值编写指标测试**

```python
def test_recall_at_five() -> None:
    assert recall_at_k(["a", "b"], ["x", "a", "y"], 5) == 0.5


def test_ndcg_rewards_earlier_relevant_evidence() -> None:
    assert ndcg_at_k(["a"], ["a", "x"], 10) > ndcg_at_k(["a"], ["x", "a"], 10)


def test_citation_precision() -> None:
    assert citation_precision(["a", "x"], ["a", "b"]) == 0.5
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/evaluation/test_metrics.py -q`

预期：FAIL，提示缺少 `evaluation.metrics`。

- [ ] **步骤 3：实现确定性指标和运行记录结构**

每条 JSONL 结果包含 `run_id`、`snapshot_id`、配置哈希、问题 id/类型、预期 URL、召回 URL/排名、答案规则得分、引用得分、忠实度得分、延迟毫秒数、输入/输出 token、模型和时间戳。

- [ ] **步骤 4：创建 60 条人工审核开发题和 20 条封存题**

`factual`、`temporal`、`comparative` 和 `comprehensive` 四类问题各包含 15 条开发题和 5 条封存题；综合题额外标记 `aggregate` 或 `relational` 子类型。每行包含问题、标准答案要点、证据 URL、适用仓库、日期范围和验收规则。增加 `evaluation/dataset/README.md`，明确选择实验方案后不得修改封存答案。实现 `check_regression.py`：任一跟踪指标相对已提交基线下降超过 `0.05` 时返回非零退出码。

- [ ] **步骤 5：运行向量和混合检索配置并提交实测输出**

运行：`python evaluation/run_eval.py --config evaluation/configs/vector.yaml --split dev`

运行：`python evaluation/run_eval.py --config evaluation/configs/hybrid.yaml --split dev`

运行：`python evaluation/summarize.py --baseline vector --candidate hybrid`

预期：生成两份不可变的结果 JSONL 和一份 Markdown 差异表；没有实测证据支持时不得把 Hybrid 设为默认方案。

```bash
git add evaluation tests/evaluation
git commit -m "test(openscout): add reproducible retrieval evaluation"
```

### 任务 9：应用显式时间/来源过滤和可选重排

**文件：**
- 新建： `docsgpt/intelligence/filters.py`
- 新建： `docsgpt/intelligence/reranker.py`
- 修改： `docsgpt/intelligence/query_service.py`
- 新建： `tests/intelligence/test_filters.py`
- 新建： `tests/intelligence/test_reranker.py`
- 新建： `evaluation/configs/hybrid-rerank.yaml`

**接口：**
- 输入：`QueryFilters` 和 Hybrid 候选 `Evidence` 对象。
- 输出：`merge_filters(explicit, inferred) -> QueryFilters`、协议 `Reranker.rerank(question, evidence, top_n) -> list[Evidence]` 和 `NoOpReranker` 回退。

- [ ] **步骤 1：编写优先级和回退测试**

```python
def test_explicit_filters_override_inferred_dates() -> None:
    merged = merge_filters(QueryFilters(date_from=date(2026, 1, 1)), QueryFilters(date_from=date(2025, 1, 1)))
    assert merged.date_from == date(2026, 1, 1)


def test_reranker_failure_preserves_hybrid_order() -> None:
    assert safe_rerank(BrokenReranker(), "q", EVIDENCE, 5) == EVIDENCE[:5]
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_filters.py tests/intelligence/test_reranker.py -q`

预期：FAIL，提示缺少模块。

- [ ] **步骤 3：实现检索前元数据过滤**

检索前将仓库、来源类型、开始日期和结束日期编译到现有来源/向量元数据过滤器中。在追踪信息中同时记录显式与推断过滤值，并使用 `source: "explicit"|"inferred"` 标明来源。

- [ ] **步骤 4：实现与服务商无关的重排接口**

```python
class Reranker(Protocol):
    def rerank(self, question: str, evidence: Sequence[Evidence], top_n: int) -> list[Evidence]:
        raise NotImplementedError


def safe_rerank(reranker: Reranker, question: str, evidence: Sequence[Evidence], top_n: int) -> list[Evidence]:
    try:
        return reranker.rerank(question, evidence, top_n)
    except Exception:
        logger.exception("reranker failed; preserving hybrid order")
        return list(evidence[:top_n])
```

只使用明确配置的重排器；不得暗中增加重量级模型依赖。在评估配置中保存服务商、模型和版本。

- [ ] **步骤 5：评估、验证并提交**

运行：`python -m pytest tests/intelligence/test_filters.py tests/intelligence/test_reranker.py tests/intelligence/test_query_service.py -q`

运行：`python evaluation/run_eval.py --config evaluation/configs/hybrid-rerank.yaml --split dev`

预期：测试 PASS，并生成一份实测 Hybrid 与 Rerank 对比结果。

```bash
git add docsgpt/intelligence evaluation/configs/hybrid-rerank.yaml tests/intelligence
git commit -m "feat(openscout): filter and rerank retrieved evidence"
```

### 任务 10：路由问题并执行确定性统计

**文件：**
- 新建： `docsgpt/intelligence/query_router.py`
- 新建： `docsgpt/intelligence/analytics.py`
- 修改： `docsgpt/storage/db/repositories/intelligence.py`
- 修改： `docsgpt/intelligence/query_service.py`
- 新建： `tests/intelligence/test_query_router.py`
- 新建： `tests/intelligence/test_analytics.py`

**接口：**
- 输入：`QueryRequest` 和按所有者隔离的项目 id。
- 输出：`RouteDecision(intent, strategy, confidence, filters)`、`QueryRouter.route(request)` 和 `AnalyticsService.run(AggregateQuery) -> AggregateResult`。

- [ ] **步骤 1：编写路由和 SQL 白名单测试**

```python
def test_low_confidence_route_falls_back_to_hybrid() -> None:
    decision = apply_route_threshold(RouteDecision(intent="relational", strategy="graphrag", confidence=0.64))
    assert decision.strategy == "hybrid"


def test_analytics_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        AnalyticsService(repo).run(AggregateQuery(metric="count", dimension="body"))
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_query_router.py tests/intelligence/test_analytics.py -q`

预期：FAIL，提示缺少路由器和统计服务。

- [ ] **步骤 3：实现受约束的路由解析**

模型或解析器输出必须通过 `RouteDecision` 校验；允许的策略只有 `hybrid`、`hybrid_rerank`、`sql_plus_hybrid`、`split_hybrid` 和 `graphrag`。校验失败或置信度 `< 0.65` 时使用 `hybrid`，并记录 `fallback_reason`。

- [ ] **步骤 4：实现白名单聚合统计**

允许的指标为 `count`、`median_comments`、`sum_reactions`；维度为 `repository`、`source_type`、`label`、`month`、`state`；排序为 `value_asc`、`value_desc`、`period_asc`。结果必须同时返回 `coverage` 和 `capped`。SQL 统计后再检索代表性证据，不得让 LLM 统计行数。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_query_router.py tests/intelligence/test_analytics.py tests/intelligence/test_query_service.py -q`

预期：五类意图均正确路由；聚合回答同时包含 SQL 数值和代表性证据。

```bash
git add docsgpt/intelligence docsgpt/storage/db/repositories/intelligence.py tests/intelligence
git commit -m "feat(openscout): route questions to retrieval and SQL"
```

### 任务 11：聚类 Issue 主题并构建有证据的产品对比

**文件：**
- 新建： `docsgpt/intelligence/topics.py`
- 新建： `docsgpt/intelligence/comparison.py`
- 修改： `docsgpt/api/user/intelligence/routes.py`
- 新建： `tests/intelligence/test_topics.py`
- 新建： `tests/intelligence/test_comparison.py`
- 修改： `tests/api/user/intelligence/test_routes.py`

**接口：**
- 输入：Issue Embedding、按所有者隔离的记录、`QueryFilters`，以及任务 10 中带引用的拆分查询链路。
- 输出：`cluster_issues(issues: Sequence[IntelligenceRecord], vectors: Mapping[str, Sequence[float]], max_clusters: int = 12) -> list[TopicCluster]`、`topic_trends(project_ids: Sequence[str], filters: QueryFilters) -> list[TopicTrend]`、`ComparisonService.compare(project_ids: Sequence[str], dimensions: Sequence[str], filters: QueryFilters) -> ComparisonResult`、`GET /api/intelligence/topics` 和 `POST /api/intelligence/comparison`。

- [ ] **步骤 1：编写确定性聚类和未知单元格测试**

```python
def test_cluster_assignment_is_stable_for_input_order(issue_vectors) -> None:
    forward = cluster_issues(ISSUES, issue_vectors)
    reverse = cluster_issues(list(reversed(ISSUES)), issue_vectors)
    assert [(c.id, sorted(c.record_ids)) for c in forward] == [
        (c.id, sorted(c.record_ids)) for c in reverse
    ]


def test_comparison_uses_unknown_without_supporting_evidence(service) -> None:
    result = service.compare(PROJECT_IDS, ["enterprise_sso"], FILTERS)
    cell = result.rows[0].cells["labring/FastGPT"]
    assert cell.status == "unknown"
    assert cell.display_label == "尚未确认"
    assert cell.evidence_ids == []
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_topics.py tests/intelligence/test_comparison.py -q`

预期：FAIL，提示缺少主题或对比模块。

- [ ] **步骤 3：使用现有 NumPy 实现确定性球面聚类**

按稳定 id 排序记录并归一化向量；使用 `k = min(max_clusters, max(2, round(sqrt(n / 2))))`；通过确定性的最远点初始化选择质心；最多执行 50 次余弦分配/更新迭代，分配不再变化时停止。从标题中频率最高的五个非停用词生成可读标签；持久化算法版本、聚类 id、记录 id、质心和快照 id。不得只为该功能引入 scikit-learn。

- [ ] **步骤 4：计算月度趋势和带引用的对比单元格**

在 PostgreSQL 中按仓库和月份统计各聚类数量。产品对比按仓库拆分每个功能维度，返回 `supported`、`not_supported` 或 `unknown`；前两种状态必须有证据，缺少证据或证据冲突时返回 `unknown`。每个单元格包含首次证据日期、社区信号数量、证据 id 和覆盖警告。

- [ ] **步骤 5：验证路由并提交**

运行：`python -m pytest tests/intelligence/test_topics.py tests/intelligence/test_comparison.py tests/api/user/intelligence/test_routes.py -q`

预期：固定数据多次运行产生相同聚类；趋势数量与 SQL 固定数据一致；每个非未知矩阵单元格均有证据。

```bash
git add docsgpt/intelligence/topics.py docsgpt/intelligence/comparison.py docsgpt/api/user/intelligence/routes.py tests/intelligence tests/api/user/intelligence/test_routes.py
git commit -m "feat(openscout): cluster feedback and compare products"
```

### 任务 12：筛选高信号 GraphRAG 数据并保证回退

**文件：**
- 新建： `docsgpt/intelligence/graph_selection.py`
- 修改： `docsgpt/intelligence/sync_service.py`
- 修改： `docsgpt/intelligence/query_service.py`
- 新建： `tests/intelligence/test_graph_selection.py`
- 修改： `tests/intelligence/test_query_service.py`
- 新建： `evaluation/configs/routed.yaml`

**接口：**
- 输入：持久化记录、现有 `extract_graph_for_source(source_id: str, user: str | None, chunks: list[dict[str, Any]], *, config: SourceConfig, request_id: str | None = None) -> dict[str, int]` 和 `GraphRAGRetriever`。
- 输出：`signal_score(comments_count, reactions_count, maxima) -> float`、`select_graph_records(records, issue_limit=300)` 和经过路由的 GraphRAG 回退追踪信息。

- [ ] **步骤 1：编写数量上限、排序、排除和回退测试**

```python
def test_graph_subset_caps_issues_but_keeps_docs_and_releases(records) -> None:
    selected = select_graph_records(records, issue_limit=300)
    assert len([r for r in selected if r.source_type == SourceType.ISSUE]) == 300
    assert all(r in selected for r in records if r.source_type in {SourceType.DOCUMENTATION, SourceType.RELEASE})


def test_graph_failure_falls_back_and_traces_reason(query_service) -> None:
    result = query_service.query(RELATIONAL_REQUEST, "u1")
    assert result.trace.strategy == "hybrid"
    assert result.trace.fallback_reason == "graphrag_unavailable"
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_graph_selection.py tests/intelligence/test_query_service.py -q`

预期：FAIL，提示缺少筛选器或回退行为。

- [ ] **步骤 3：实现归一化高信号排序**

```python
def signal_score(comments: int, reactions: int, max_comments: int, max_reactions: int) -> float:
    comment_score = comments / max(1, max_comments)
    reaction_score = reactions / max(1, max_reactions)
    return 0.6 * comment_score + 0.4 * reaction_score
```

依次按得分降序、`updated_at` 和外部 id 排序，保证同分结果确定。

- [ ] **步骤 4：接入选择性图谱抽取和查询回退**

图谱抽取在向量索引完成后异步运行。查询服务只对 `relational` 使用 GraphRAG；功能禁用、未完成、失败或超时时，执行一次 Hybrid 并记录准确原因。统计模块不得接收来自图谱的记录。

- [ ] **步骤 5：运行路由实验并提交**

运行：`python -m pytest tests/intelligence/test_graph_selection.py tests/intelligence/test_query_service.py -q`

运行：`python evaluation/run_eval.py --config evaluation/configs/routed.yaml --split dev`

预期：测试 PASS；第三组实验完成统一 Hybrid 与路由 SQL/GraphRAG 对比，并包含延迟和 token 成本。

```bash
git add docsgpt/intelligence evaluation/configs/routed.yaml tests/intelligence
git commit -m "feat(openscout): route relational questions through GraphRAG"
```

### 任务 13：强制引用并计算逐结论确定性可信度

**文件：**
- 新建： `docsgpt/intelligence/claims.py`
- 新建： `docsgpt/intelligence/confidence.py`
- 修改： `docsgpt/intelligence/query_service.py`
- 新建： `tests/intelligence/test_claims.py`
- 新建： `tests/intelligence/test_confidence.py`

**接口：**
- 输入：生成的结论、证据、覆盖范围和冲突标记。
- 输出：`validate_claims(claims: Sequence[Claim], evidence: Sequence[Evidence], coverage: Coverage) -> ClaimValidation`、`confidence_for_claim(claim: Claim, evidence: Sequence[Evidence], coverage: Coverage, has_conflict: bool) -> Confidence`，以及重新生成一次后降级的行为。

- [ ] **步骤 1：将规格规则编码为参数化测试**

```python
@pytest.mark.parametrize("case,expected", [
    (official_release_case(), Confidence.HIGH),
    (complete_sql_case(), Confidence.HIGH),
    (two_author_issue_case(), Confidence.MEDIUM),
    (single_issue_case(), Confidence.LOW),
    (conflict_case(), Confidence.LOW),
    (inference_case(), Confidence.LOW),
])
def test_confidence_rules(case, expected) -> None:
    assert confidence_for_claim(**case) == expected
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_claims.py tests/intelligence/test_confidence.py -q`

预期：FAIL，提示缺少可信层模块。

- [ ] **步骤 3：实现证据 id 校验和冲突保留**

拒绝响应中不存在的证据 id。事实或统计没有有效证据时只触发一次重新生成；仍无效则返回确定性统计、证据卡片和拒答文案 `当前收录数据无法支持该结论`。

- [ ] **步骤 4：逐条结论计算可信度**

根据来源类型、不同 Issue 作者数量、覆盖完整性、冲突、数据时效和结论类型计算。不得接受 LLM 提供的可信度数字。保留冲突结论并同时展示双方来源日期。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_claims.py tests/intelligence/test_confidence.py tests/intelligence/test_query_service.py -q`

预期：PASS；五个固定演示问题中不存在无引用的事实性结论。

```bash
git add docsgpt/intelligence/claims.py docsgpt/intelligence/confidence.py docsgpt/intelligence/query_service.py tests/intelligence
git commit -m "feat(openscout): enforce evidence and claim confidence"
```

### 任务 14：生成统一报告模型并导出 Markdown/PDF

**文件：**
- 新建： `docsgpt/intelligence/report_service.py`
- 修改： `docsgpt/api/user/intelligence/routes.py`
- 新建： `tests/intelligence/test_report_service.py`
- 修改： `tests/api/user/intelligence/test_routes.py`

**接口：**
- 输入：已保存的 `QueryResult` 对象和对比/统计结果。
- 输出：`ReportDocument`、`ReportService.create(user_id: str, project_ids: Sequence[str], results: Sequence[QueryResult]) -> dict`、`render_markdown(report: ReportDocument) -> str`、`render_pdf(report: ReportDocument) -> bytes`、`POST /api/intelligence/reports`、`GET /api/intelligence/reports/<id>` 和 `GET /api/intelligence/reports/<id>/download?format=markdown|pdf`。

- [ ] **步骤 1：编写渲染一致性和重试测试**

```python
def test_markdown_and_pdf_share_source_ids(report) -> None:
    markdown = render_markdown(report)
    pdf_text = extract_pdf_text(render_pdf(report))
    assert "github.com/langgenius/dify" in markdown
    assert "github.com/langgenius/dify" in pdf_text


def test_export_retry_does_not_rerun_query(report_service, query_service) -> None:
    report_service.export(REPORT_ID, "pdf")
    report_service.export(REPORT_ID, "pdf")
    query_service.query.assert_not_called()
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py -q`

预期：FAIL，提示缺少报告服务或路由。

- [ ] **步骤 3：实现统一报告数据结构**

章节固定为：执行摘要、功能对比、反馈趋势、产品机会线索、风险与证据限制、完整来源。渲染前先保存结构化 JSON；渲染器只接受 `ReportDocument`。

- [ ] **步骤 4：实现需要认证的导出接口**

Markdown 使用 UTF-8 附件响应；PDF 使用 ReportLab 和存放在合规资源目录中的内嵌中日韩字体，或复用项目现有字体。导出失败时保留报告记录，返回可重试的 500，且不得重新执行查询。

- [ ] **步骤 5：验证并提交**

运行：`python -m pytest tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py -q`

预期：PASS；Markdown 和从 PDF 提取的文本包含相同章节标题与来源 URL。

```bash
git add docsgpt/intelligence/report_service.py docsgpt/api/user/intelligence/routes.py tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py
git commit -m "feat(openscout): export evidence-backed intelligence reports"
```

### 任务 15：构建强类型前端状态、路由、概览和工作台

**文件：**
- 新建： `frontend/src/intelligence/types.ts`
- 新建： `frontend/src/intelligence/intelligenceService.ts`
- 新建： `frontend/src/intelligence/intelligenceSlice.ts`
- 新建： `frontend/src/intelligence/Overview.tsx`
- 新建： `frontend/src/intelligence/Workbench.tsx`
- 新建： `frontend/src/intelligence/intelligenceSlice.test.ts`
- 新建： `frontend/src/intelligence/Overview.test.tsx`
- 新建： `frontend/src/intelligence/Workbench.test.tsx`
- 修改： `frontend/src/api/endpoints.ts`
- 修改： `frontend/src/store.ts`
- 修改： `frontend/src/App.tsx`
- 修改： `frontend/src/Navigation.tsx`

**接口：**
- 输入：任务 7 的 API 和精确 `QueryResult` JSON 字段。
- 输出：Redux `intelligence` 状态、`/intelligence` 概览路由、`/intelligence/workbench` 路由、过滤控件和查询分发。

- [ ] **步骤 1：编写 reducer 和可见状态测试**

```tsx
it('shows capped coverage as a warning', async () => {
  render(<Overview />, {preloadedState: cappedOverviewState});
  expect(screen.getByText(/已达到 1,000 条 Issue 上限/)).toBeInTheDocument();
});

it('sends explicit filters with the question', async () => {
  render(<Workbench />);
  await userEvent.click(screen.getByLabelText('Dify'));
  await userEvent.type(screen.getByLabelText('研究问题'), '最近有哪些变化？');
  await userEvent.click(screen.getByRole('button', {name: '开始分析'}));
  expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({filters: {repositories: ['langgenius/dify']}}));
});
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`cd frontend && npm test -- --run src/intelligence/intelligenceSlice.test.ts src/intelligence/Overview.test.tsx src/intelligence/Workbench.test.tsx`

预期：FAIL，因为功能目录和路由尚不存在。

- [ ] **步骤 3：实现 API 类型和 Redux 状态**

严格复用后端字段名；状态包含 `overview`、`filters`、`question`、`queryResult`、`requestStatus` 和 `error`。复用现有 API 基础配置和错误处理，在 `/api/intelligence` 下增加接口常量。

- [ ] **步骤 4：实现概览和工作台状态**

概览卡片展示文档/Issue/Release 数量、覆盖范围、最近同步、最新版本、主题和达到上限/部分完成警告。工作台提供仓库多选、日期范围、来源类型、问题类型和五个固定推荐问题，并包含加载、空数据、部分完成和错误文案。

- [ ] **步骤 5：验证并提交**

运行：`cd frontend && npm test -- --run src/intelligence`

运行：`cd frontend && npm run lint`

预期：测试 PASS，lint 退出码为 0。

```bash
git add frontend/src/intelligence frontend/src/api/endpoints.ts frontend/src/store.ts frontend/src/App.tsx frontend/src/Navigation.tsx
git commit -m "feat(openscout): add intelligence overview and workbench"
```

### 任务 16：展示结论、证据、产品对比和报告

**文件：**
- 新建： `frontend/src/intelligence/ClaimCard.tsx`
- 新建： `frontend/src/intelligence/EvidencePanel.tsx`
- 新建： `frontend/src/intelligence/ComparisonMatrix.tsx`
- 新建： `frontend/src/intelligence/ReportView.tsx`
- 新建： `frontend/src/intelligence/ClaimCard.test.tsx`
- 新建： `frontend/src/intelligence/ComparisonMatrix.test.tsx`
- 新建： `frontend/src/intelligence/ReportView.test.tsx`
- 修改： `frontend/src/intelligence/Workbench.tsx`

**接口：**
- 输入：`QueryResult`、对比单元格和报告接口。
- 输出：按照 `summary -> analysis -> statistics -> evidence` 排序的结果、逐结论类型/可信度、可展开证据、对比单元格和下载操作。

- [ ] **步骤 1：编写可信信息展示测试**

```tsx
it('renders unsupported comparison cells as 尚未确认', () => {
  render(<ComparisonMatrix rows={[unknownFeatureRow]} />);
  expect(screen.getByText('尚未确认')).toBeInTheDocument();
});

it('opens every claim evidence source', async () => {
  render(<ClaimCard claim={claim} evidence={evidence} />);
  await userEvent.click(screen.getByRole('button', {name: /查看 2 条证据/}));
  expect(screen.getAllByRole('link')).toHaveLength(2);
});
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`cd frontend && npm test -- --run src/intelligence/ClaimCard.test.tsx src/intelligence/ComparisonMatrix.test.tsx src/intelligence/ReportView.test.tsx`

预期：FAIL，因为组件尚不存在。

- [ ] **步骤 3：实现证据优先的结果组件**

标准图标使用 `lucide-react`。每张证据卡展示来源类型、仓库、日期/版本、摘要和外部 GitHub 链接。展示 `事实`、`统计` 或 `AI 推断`，以及确定性的 `低/中/高` 可信度。在结果顶部展示数据过期和 GraphRAG 回退提示。

- [ ] **步骤 4：实现矩阵和报告流程**

矩阵单元格展示支持状态、首个证据日期、社区信号数量和可展开来源。未知单元格显示 `尚未确认`。ReportView 展示六个固定报告章节，并在不重新运行分析的情况下触发 Markdown/PDF 下载。

- [ ] **步骤 5：验证并提交**

运行：`cd frontend && npm test -- --run src/intelligence`

运行：`cd frontend && npm run build`

预期：测试 PASS，生产构建成功。

```bash
git add frontend/src/intelligence
git commit -m "feat(openscout): present evidence comparisons and reports"
```

### 任务 17：锁定阶段 A 质量门槛和作品集证据

**文件：**
- 新建： `tests/integration/test_openscout_stage_a.py`
- 新建： `evaluation/demo/questions.json`
- 新建： `evaluation/results/stage-a-summary.md`
- 新建： `docs/openscout/architecture.md`
- 新建： `docs/openscout/limitations.md`
- 新建： `README-openscout.md`
- 修改： `docs/openscout/decision-log.md`

**接口：**
- 输入：冻结快照、80 条问题数据集和阶段 A 全部 API/界面。
- 输出：一套可重复执行的五分钟演示、实测门槛报告、架构/限制文档、截图/视频清单和版本标签资格。

- [ ] **步骤 1：编写端到端验收测试**

```python
def test_stage_a_demo_has_no_uncited_fact(openscout_client) -> None:
    for scenario in load_demo_scenarios("evaluation/demo/questions.json"):
        result = openscout_client.query(scenario)
        assert result["claims"]
        assert all(claim["evidence_ids"] for claim in result["claims"] if claim["kind"] in {"fact", "statistic"})
        assert all(e["source_url"].startswith("https://github.com/") for e in result["evidence"])
```

- [ ] **步骤 2：针对固定快照运行集成测试**

运行：`KMP_DUPLICATE_LIB_OK=TRUE python -m pytest tests/integration/test_openscout_stage_a.py -q`

预期：五个演示场景全部 PASS：发现趋势、查看代表性 Issues、分析 Release 关系、对比三个产品和生成报告。

- [ ] **步骤 3：运行一次封存测试集并生成门槛报告**

运行：`python evaluation/run_eval.py --config evaluation/configs/routed.yaml --split holdout --freeze`

运行：`python evaluation/summarize.py --release-gates --output evaluation/results/stage-a-summary.md`

运行：`python evaluation/check_regression.py --baseline evaluation/results/baseline.json --candidate evaluation/results/stage-a.json --max-drop 0.05`

预期：报告包含事实题正确率、引用准确率、复杂问题成功率、非 GraphRAG 平均延迟、token 成本和各门槛是否通过；只有所有跟踪指标下降不超过 5 个百分点时，回归检查才返回 0。之后不得修改封存问题。

- [ ] **步骤 4：只记录实测结论并保存证明材料**

`README-openscout.md` 必须披露 DocsGPT 底座、列出 OpenScout 原创工作、展示三组实验、链接失败案例、说明 GitHub Issue 抽样偏差，并使用摘要中的实测值。按照 PR 要求保存截图或短视频。

- [ ] **步骤 5：运行完整验证并提交**

运行：`ruff check .`

运行：`KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`

运行：`cd frontend && npm run lint`

运行：`cd frontend && npm run build`

预期：所有命令成功。若质量门槛未通过，保留实测结果并删除对应成功表述，不得修改门槛。

```bash
git add tests/integration evaluation docs/openscout README-openscout.md
git commit -m "docs(openscout): publish measured stage A portfolio evidence"
git tag openscout-stage-a
```

## 阶段 A 自检记录

- 规格覆盖：采集上限、四类来源、幂等、部分成功、Hybrid/Rerank/路由实验、SQL 统计、选择性 GraphRAG、证据规则、可信度、矩阵、Markdown/PDF、覆盖警告、五分钟演示和发布门槛均已分配到任务。
- 有意排除：任意仓库、增量删除确认、公开分享链接、定时同步和用户研究属于独立的阶段 B 计划。
- 类型一致性：`QueryResult`、`Evidence`、`Claim`、`Coverage` 和 `SyncSummary` 在任务 1 定义；`RouteDecision` 在任务 10 定义；后续任务不得改名。
- 占位符扫描：所有任务均包含精确文件、接口、测试、命令、预期结果和提交边界，不存在未完成的实现标记。
