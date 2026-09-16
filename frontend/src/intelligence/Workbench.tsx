import {
  ArrowLeft,
  CalendarDays,
  Check,
  CircleAlert,
  Loader2,
  Send,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Button } from '../components/ui/button';
import { selectToken } from '../preferences/preferenceSlice';
import { type AppDispatch } from '../store';
import {
  loadProjects,
  queryIntelligence,
  selectIntelligence,
  setFilters,
  setQuestion,
} from './intelligenceSlice';
import type { QueryIntent, SourceType } from './types';

const REPOSITORIES = [
  { label: 'Dify', value: 'langgenius/dify' },
  { label: 'RAGFlow', value: 'infiniflow/ragflow' },
  { label: 'FastGPT', value: 'labring/FastGPT' },
] as const;

const SOURCE_OPTIONS: { label: string; value: SourceType }[] = [
  { label: '文档', value: 'documentation' },
  { label: 'Issue', value: 'issue' },
  { label: '评论', value: 'issue_comment' },
  { label: 'Release', value: 'release' },
];

const INTENT_OPTIONS: { label: string; value: QueryIntent }[] = [
  { label: '事实', value: 'factual' },
  { label: '时间变化', value: 'temporal' },
  { label: '产品对比', value: 'comparative' },
  { label: '精确统计', value: 'aggregate' },
  { label: '关系分析', value: 'relational' },
];

const RECOMMENDED_QUESTIONS: {
  intent: QueryIntent;
  label: string;
  question: string;
}[] = [
  {
    intent: 'aggregate',
    label: '发现趋势',
    question: '最近哪些 Issue 主题最活跃？',
  },
  {
    intent: 'factual',
    label: '找代表性问题',
    question: '有哪些高频 Issue 仍然没有解决？',
  },
  {
    intent: 'temporal',
    label: '连接版本变化',
    question: '最近的 Release 解决了哪些问题？',
  },
  {
    intent: 'comparative',
    label: '比较产品',
    question: 'Dify、RAGFlow 和 FastGPT 在 SSO 方面有什么差异？',
  },
  {
    intent: 'relational',
    label: '追踪关系',
    question: '哪些 Issue 与最近的版本发布直接相关？',
  },
];

function sourceCount(
  counts: Partial<Record<SourceType, number>>,
  sourceType: SourceType,
): string {
  return new Intl.NumberFormat('zh-CN').format(counts[sourceType] ?? 0);
}

function statusLabel(status: string): string {
  return (
    {
      draft: '草稿',
      syncing: '同步中',
      ready: '已就绪',
      partial: '部分完成',
      failed: '同步失败',
    }[status] ?? status
  );
}

export default function Workbench() {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const {
    projects,
    filters,
    question,
    queryResult,
    requestStatus,
    projectsStatus,
    error,
  } = useSelector(selectIntelligence);
  const [questionType, setQuestionType] = useState<QueryIntent>('factual');

  useEffect(() => {
    if (projectsStatus === 'idle') dispatch(loadProjects());
  }, [dispatch, projectsStatus, token]);

  const toggleRepository = (repository: string) => {
    const repositories = filters.repositories.includes(repository)
      ? filters.repositories.filter((value) => value !== repository)
      : [...filters.repositories, repository];
    dispatch(setFilters({ repositories }));
  };

  const toggleSourceType = (sourceType: SourceType) => {
    const sourceTypes = filters.source_types.includes(sourceType)
      ? filters.source_types.filter((value) => value !== sourceType)
      : [...filters.source_types, sourceType];
    dispatch(setFilters({ source_types: sourceTypes }));
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    dispatch(queryIntelligence({ question, filters }));
  };

  const selectedRepositoryLabel = filters.repositories.length
    ? filters.repositories
        .map(
          (repository) =>
            REPOSITORIES.find((option) => option.value === repository)?.label ??
            repository,
        )
        .join('、')
    : '全部固定产品';

  return (
    <div className="min-h-full bg-[#f6f4ed] px-5 py-8 text-[#20241f] md:px-10 md:py-10 lg:px-14 dark:bg-[#111511] dark:text-[#f2f3e9]">
      <div className="mx-auto max-w-6xl">
        <header className="border-b border-black/10 pb-7 dark:border-white/10">
          <Link
            to="/intelligence"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-2 text-sm transition-colors"
          >
            <ArrowLeft className="size-4" />
            返回产品情报
          </Link>
          <div className="mt-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="mb-3 flex items-center gap-2 font-mono text-[11px] tracking-[0.2em] text-emerald-700 uppercase dark:text-emerald-300">
                <SlidersHorizontal className="size-4" />
                OpenScout / workbench
              </div>
              <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
                研究工作台
              </h1>
              <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-6">
                先声明研究范围，再提出问题。每次分析都会把过滤条件和数据覆盖一起返回。
              </p>
            </div>
            <div className="rounded-full border border-black/10 bg-white/70 px-4 py-2 font-mono text-xs dark:border-white/10 dark:bg-white/[0.04]">
              scope · {selectedRepositoryLabel}
            </div>
          </div>
        </header>

        <div className="mt-8 grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="h-fit rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                  Research scope
                </p>
                <h2 className="mt-2 text-lg font-semibold">过滤条件</h2>
              </div>
              <SlidersHorizontal className="text-muted-foreground size-4" />
            </div>

            <fieldset className="mt-7">
              <legend className="text-foreground text-sm font-medium">
                仓库
              </legend>
              <div className="mt-3 space-y-2">
                {REPOSITORIES.map((repository) => {
                  const project = projects.find(
                    (candidate) => candidate.repository === repository.value,
                  );
                  const checked = filters.repositories.includes(
                    repository.value,
                  );
                  return (
                    <label
                      key={repository.value}
                      className="group flex cursor-pointer items-center gap-3 rounded-xl border border-transparent px-2 py-2 transition-colors hover:border-black/10 hover:bg-black/[0.03] dark:hover:border-white/10 dark:hover:bg-white/[0.04]"
                    >
                      <span className="relative flex size-4 shrink-0 items-center justify-center">
                        <input
                          type="checkbox"
                          aria-label={repository.label}
                          checked={checked}
                          onChange={() => toggleRepository(repository.value)}
                          className="peer size-4 cursor-pointer appearance-none rounded border border-black/25 bg-transparent checked:border-emerald-600 checked:bg-emerald-600 dark:border-white/30"
                        />
                        <Check className="pointer-events-none absolute hidden size-3 text-white peer-checked:block" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="text-foreground block text-sm">
                          {repository.label}
                        </span>
                        <span className="text-muted-foreground block truncate font-mono text-[10px]">
                          {repository.value}
                        </span>
                      </span>
                      {project && (
                        <span className="text-muted-foreground shrink-0 text-[10px]">
                          {statusLabel(project.status)}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <fieldset className="mt-7">
              <legend className="text-foreground text-sm font-medium">
                来源类型
              </legend>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {SOURCE_OPTIONS.map((source) => {
                  const checked = filters.source_types.includes(source.value);
                  return (
                    <label
                      key={source.value}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-black/[0.04] dark:hover:bg-white/[0.05]"
                    >
                      <input
                        type="checkbox"
                        aria-label={source.label}
                        checked={checked}
                        onChange={() => toggleSourceType(source.value)}
                        className="size-3.5 accent-emerald-600"
                      />
                      <span>{source.label}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <fieldset className="mt-7">
              <legend className="text-foreground flex items-center gap-2 text-sm font-medium">
                <CalendarDays className="text-muted-foreground size-4" />
                日期范围
              </legend>
              <div className="mt-3 space-y-2">
                <label className="text-muted-foreground block text-xs">
                  开始日期
                  <input
                    type="date"
                    aria-label="开始日期"
                    value={filters.date_from ?? ''}
                    onChange={(event) =>
                      dispatch(
                        setFilters({ date_from: event.target.value || null }),
                      )
                    }
                    className="border-border bg-background text-foreground mt-1 h-9 w-full rounded-lg border px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/30"
                  />
                </label>
                <label className="text-muted-foreground block text-xs">
                  结束日期
                  <input
                    type="date"
                    aria-label="结束日期"
                    value={filters.date_to ?? ''}
                    onChange={(event) =>
                      dispatch(
                        setFilters({ date_to: event.target.value || null }),
                      )
                    }
                    className="border-border bg-background text-foreground mt-1 h-9 w-full rounded-lg border px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/30"
                  />
                </label>
              </div>
            </fieldset>

            <div className="mt-7 border-t border-dashed border-black/10 pt-4 dark:border-white/10">
              <p className="text-muted-foreground text-xs leading-5">
                未选择仓库或来源时，查询会使用全部已同步数据。显式条件优先于问题文字中的推断。
              </p>
            </div>
          </aside>

          <main className="min-w-0">
            <form
              onSubmit={handleSubmit}
              className="rounded-2xl border border-black/10 bg-white/70 p-6 shadow-[0_18px_40px_-30px_rgba(30,40,30,0.75)] dark:border-white/10 dark:bg-white/[0.04]"
            >
              <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
                <Sparkles className="size-4" />
                <span className="font-mono text-[11px] tracking-[0.18em] uppercase">
                  Ask the corpus
                </span>
              </div>
              <label
                htmlFor="research-question"
                className="text-foreground mt-5 block text-sm font-medium"
              >
                研究问题
              </label>
              <textarea
                id="research-question"
                aria-label="研究问题"
                value={question}
                onChange={(event) => dispatch(setQuestion(event.target.value))}
                placeholder="例如：最近的 Release 主要解决了哪些用户问题？"
                rows={5}
                className="border-border bg-background text-foreground placeholder:text-muted-foreground mt-2 w-full resize-y rounded-xl border px-4 py-3 text-base leading-6 outline-none focus-visible:border-emerald-600/70 focus-visible:ring-4 focus-visible:ring-emerald-600/10"
              />
              <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <label className="text-muted-foreground block text-xs">
                  问题类型
                  <select
                    aria-label="问题类型"
                    value={questionType}
                    onChange={(event) =>
                      setQuestionType(event.target.value as QueryIntent)
                    }
                    className="border-border bg-background text-foreground mt-1 block h-9 rounded-lg border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/30"
                  >
                    {INTENT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  type="submit"
                  disabled={requestStatus === 'loading'}
                  className="w-full rounded-full bg-[#1f6b4d] px-5 text-white hover:bg-[#18563e] sm:w-auto"
                >
                  {requestStatus === 'loading' ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Send className="size-4" />
                  )}
                  开始分析
                </Button>
              </div>
            </form>

            <section className="mt-6 rounded-2xl border border-black/10 bg-white/50 p-6 dark:border-white/10 dark:bg-white/[0.025]">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                    Suggested prompts
                  </p>
                  <h2 className="mt-2 text-lg font-semibold">
                    从一个研究动作开始
                  </h2>
                </div>
                <span className="text-muted-foreground hidden font-mono text-xs sm:block">
                  05 prompts
                </span>
              </div>
              <div className="mt-5 grid gap-2 sm:grid-cols-2">
                {RECOMMENDED_QUESTIONS.map((recommendation) => (
                  <button
                    key={recommendation.question}
                    type="button"
                    onClick={() => {
                      setQuestionType(recommendation.intent);
                      dispatch(setQuestion(recommendation.question));
                    }}
                    className="group flex items-center justify-between gap-3 rounded-xl border border-black/10 bg-white/60 px-4 py-3 text-left text-sm transition-colors hover:border-emerald-600/50 hover:bg-emerald-50/70 dark:border-white/10 dark:bg-white/[0.035] dark:hover:bg-emerald-950/20"
                  >
                    <span>
                      <span className="text-muted-foreground mb-1 block font-mono text-[10px] tracking-[0.12em] uppercase">
                        {recommendation.label}
                      </span>
                      <span className="text-foreground leading-5">
                        {recommendation.question}
                      </span>
                    </span>
                    <ArrowLeft className="text-muted-foreground size-4 rotate-180 transition-transform group-hover:translate-x-0.5 group-hover:text-emerald-700" />
                  </button>
                ))}
              </div>
            </section>

            <section
              className="mt-6 rounded-2xl border border-black/10 bg-white/70 p-6 dark:border-white/10 dark:bg-white/[0.04]"
              aria-live="polite"
            >
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                    Analysis output
                  </p>
                  <h2 className="mt-2 text-lg font-semibold">结果预览</h2>
                </div>
                {queryResult && (
                  <span className="text-muted-foreground font-mono text-xs">
                    {queryResult.latency_ms} ms
                  </span>
                )}
              </div>

              {projectsStatus === 'failed' && projects.length === 0 ? (
                <div className="mt-6 flex items-start gap-3 rounded-xl border border-red-300/70 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-100">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" />
                  <span>{error ?? '无法读取项目清单，请稍后重试。'}</span>
                </div>
              ) : requestStatus === 'loading' ? (
                <div
                  className="text-muted-foreground mt-8 flex items-center gap-3 text-sm"
                  role="status"
                >
                  <Loader2 className="size-4 animate-spin" />
                  正在检索并整理证据…
                </div>
              ) : requestStatus === 'failed' ? (
                <div className="mt-6 flex items-start gap-3 rounded-xl border border-red-300/70 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-100">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" />
                  <span>
                    {error ?? '分析失败，请检查问题和数据范围后重试。'}
                  </span>
                </div>
              ) : !queryResult ? (
                <div className="border-border text-muted-foreground mt-6 rounded-xl border border-dashed p-8 text-center text-sm leading-6">
                  选择范围并提出问题，开始生成有证据的产品情报。
                </div>
              ) : (
                <div className="mt-6">
                  {queryResult.coverage.capped && (
                    <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-100">
                      <CircleAlert className="mt-0.5 size-4 shrink-0" />
                      <span>当前结果来自部分覆盖，解读时请保留谨慎。</span>
                    </div>
                  )}
                  <p className="text-foreground text-base leading-7 whitespace-pre-wrap">
                    {queryResult.answer}
                  </p>
                  <div className="mt-6 grid gap-3 text-xs sm:grid-cols-3">
                    <div className="rounded-xl bg-black/[0.04] p-3 dark:bg-white/[0.05]">
                      <span className="text-muted-foreground block">
                        路由意图
                      </span>
                      <span className="text-foreground mt-1 block font-mono">
                        {queryResult.trace.intent}
                      </span>
                    </div>
                    <div className="rounded-xl bg-black/[0.04] p-3 dark:bg-white/[0.05]">
                      <span className="text-muted-foreground block">
                        结论 / 证据
                      </span>
                      <span className="text-foreground mt-1 block font-mono">
                        {queryResult.claims.length} /{' '}
                        {queryResult.evidence.length}
                      </span>
                    </div>
                    <div className="rounded-xl bg-black/[0.04] p-3 dark:bg-white/[0.05]">
                      <span className="text-muted-foreground block">
                        覆盖记录
                      </span>
                      <span className="text-foreground mt-1 block font-mono">
                        {Object.values(queryResult.coverage.counts).reduce(
                          (total, count) => total + (count ?? 0),
                          0,
                        )}
                      </span>
                    </div>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {SOURCE_OPTIONS.map((source) => (
                      <span
                        key={source.value}
                        className="text-muted-foreground rounded-full border border-black/10 px-3 py-1 font-mono text-[10px] dark:border-white/10"
                      >
                        {source.label} ·{' '}
                        {sourceCount(queryResult.coverage.counts, source.value)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </main>
        </div>
      </div>
    </div>
  );
}
