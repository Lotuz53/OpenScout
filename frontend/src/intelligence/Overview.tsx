import {
  ArrowUpRight,
  BookOpen,
  Boxes,
  CalendarDays,
  CircleAlert,
  Clock3,
  MessageSquareText,
  PackageCheck,
  Plus,
  Radar,
} from 'lucide-react';
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Button } from '../components/ui/button';
import Spinner from '../components/Spinner';
import { selectToken } from '../preferences/preferenceSlice';
import { type AppDispatch } from '../store';
import {
  loadOverview,
  loadProjects,
  selectIntelligenceOverview,
  selectIntelligenceProjects,
  selectIntelligence,
} from './intelligenceSlice';
import type {
  IntelligenceOverview as OverviewData,
  IntelligenceProject,
  SourceType,
  TopicTrend,
} from './types';

const SOURCE_CARDS: {
  key: SourceType;
  label: string;
  icon: typeof BookOpen;
  accent: string;
}[] = [
  {
    key: 'documentation',
    label: '文档',
    icon: BookOpen,
    accent: 'text-sky-600 dark:text-sky-300',
  },
  {
    key: 'issue',
    label: 'Issue',
    icon: MessageSquareText,
    accent: 'text-amber-600 dark:text-amber-300',
  },
  {
    key: 'release',
    label: 'Release',
    icon: PackageCheck,
    accent: 'text-emerald-600 dark:text-emerald-300',
  },
];

function formatNumber(value: number | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(value ?? 0);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '尚未同步';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatDateRange(overview: OverviewData): string {
  const { date_from: dateFrom, date_to: dateTo } = overview.coverage;
  if (!dateFrom || !dateTo) return '等待数据覆盖范围';
  return `${dateFrom} → ${dateTo}`;
}

function statusLabel(status: IntelligenceProject['status']): string {
  return {
    draft: '草稿',
    syncing: '同步中',
    ready: '已就绪',
    partial: '部分完成',
    failed: '同步失败',
  }[status];
}

function statusClass(status: IntelligenceProject['status']): string {
  return {
    draft: 'bg-muted text-muted-foreground',
    syncing: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-200',
    ready:
      'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200',
    partial:
      'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200',
    failed: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  }[status];
}

function TopicSignal({ topic }: { topic: TopicTrend }) {
  return (
    <li className="flex items-center justify-between gap-3 border-b border-dashed border-black/10 py-3 last:border-0 dark:border-white/10">
      <div className="min-w-0">
        <p className="text-foreground truncate text-sm font-medium">
          {topic.label}
        </p>
        <p className="text-muted-foreground mt-1 truncate font-mono text-[11px] uppercase">
          {topic.repository} · {topic.month}
        </p>
      </div>
      <span className="text-foreground shrink-0 font-mono text-sm tabular-nums">
        {formatNumber(topic.count)}
      </span>
    </li>
  );
}

export default function IntelligenceOverview() {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const { overviewStatus, projectsStatus, error } =
    useSelector(selectIntelligence);
  const overview = useSelector(selectIntelligenceOverview);
  const projects = useSelector(selectIntelligenceProjects);

  useEffect(() => {
    if (overviewStatus === 'idle') dispatch(loadOverview());
  }, [dispatch, overviewStatus, token]);

  useEffect(() => {
    if (projectsStatus === 'idle') dispatch(loadProjects());
  }, [dispatch, projectsStatus, token]);

  if (overviewStatus === 'loading' && !overview) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <div
          className="text-muted-foreground flex items-center gap-3 text-sm"
          role="status"
        >
          <Spinner size="small" />
          正在整理项目情报…
        </div>
      </div>
    );
  }

  if (overviewStatus === 'failed' && !overview) {
    return (
      <div className="mx-auto flex min-h-full max-w-3xl flex-col items-start justify-center gap-4 p-8">
        <div className="flex items-center gap-2 text-red-600 dark:text-red-300">
          <CircleAlert className="size-5" />
          <h1 className="text-lg font-semibold">暂时无法加载产品情报</h1>
        </div>
        <p className="text-muted-foreground text-sm">
          {error ?? '请稍后重试。'}
        </p>
        <Button type="button" onClick={() => dispatch(loadOverview())}>
          重新加载
        </Button>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="text-muted-foreground flex min-h-full items-center justify-center p-8 text-sm">
        暂无可用的产品情报。
      </div>
    );
  }

  const issueCount = overview.counts.issue ?? 0;
  const capped =
    overview.capped === true ||
    overview.coverage.capped === true ||
    issueCount >= 1000;
  const partial =
    (overview.statuses.partial ?? 0) > 0 ||
    (overview.statuses.syncing ?? 0) > 0 ||
    (overview.statuses.failed ?? 0) > 0;
  const latestVersion =
    overview.latest_version ??
    projects.find((project) => project.latest_version)?.latest_version ??
    '尚未同步';
  const topics = overview.topics?.slice(0, 5) ?? [];

  return (
    <div className="min-h-full bg-[#f6f4ed] px-5 py-8 text-[#20241f] md:px-10 md:py-10 lg:px-14 dark:bg-[#111511] dark:text-[#f2f3e9]">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-col gap-7 border-b border-black/10 pb-8 md:flex-row md:items-end md:justify-between dark:border-white/10">
          <div>
            <div className="mb-4 flex items-center gap-2 font-mono text-[11px] tracking-[0.22em] text-emerald-700 uppercase dark:text-emerald-300">
              <Radar className="size-4" />
              OpenScout / field note 01
            </div>
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
              产品情报
            </h1>
            <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-6">
              把固定产品范围内的文档、Issue 与 Release 组织成可追溯的研究起点。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              asChild
              variant="outline"
              className="w-fit rounded-full px-4"
            >
              <Link to="/intelligence/setup">
                <Plus className="size-4" />
                添加公开仓库
              </Link>
            </Button>
            <Button asChild className="w-fit rounded-full px-5">
              <Link to="/intelligence/workbench">
                进入研究工作台
                <ArrowUpRight className="size-4" />
              </Link>
            </Button>
          </div>
        </header>

        {capped && (
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-amber-300/80 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-100">
            <CircleAlert className="mt-0.5 size-4 shrink-0" />
            <p>已达到 1,000 条 Issue 上限，趋势与结论只覆盖当前采集范围。</p>
          </div>
        )}
        {partial && (
          <div className="mt-3 flex items-start gap-3 rounded-xl border border-sky-300/70 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-700/60 dark:bg-sky-950/30 dark:text-sky-100">
            <Clock3 className="mt-0.5 size-4 shrink-0" />
            <p>部分项目尚未完成同步，当前概览不代表完整覆盖。</p>
          </div>
        )}

        <section
          className="mt-8 grid gap-3 sm:grid-cols-3"
          aria-label="数据总量"
        >
          {SOURCE_CARDS.map(({ key, label, icon: Icon, accent }) => (
            <article
              key={key}
              className="group rounded-2xl border border-black/10 bg-white/70 p-5 shadow-[0_14px_30px_-24px_rgba(30,40,30,0.65)] transition-transform hover:-translate-y-0.5 dark:border-white/10 dark:bg-white/[0.04]"
              data-source-type={key}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`rounded-lg bg-black/[0.04] p-2 ${accent} dark:bg-white/[0.06]`}
                >
                  <Icon className="size-4" />
                </span>
                <span className="font-mono text-[10px] tracking-[0.18em] text-black/40 uppercase dark:text-white/40">
                  0{SOURCE_CARDS.findIndex((card) => card.key === key) + 1}
                </span>
              </div>
              <p className="text-muted-foreground mt-7 text-sm">{label}</p>
              <p className="mt-1 font-mono text-3xl font-medium tabular-nums">
                {formatNumber(overview.counts[key])}
              </p>
            </article>
          ))}
        </section>

        <section className="mt-3 grid gap-3 md:grid-cols-3">
          <article className="rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
              <CalendarDays className="size-4" />
              <span className="font-mono text-[11px] tracking-[0.16em] uppercase">
                覆盖范围
              </span>
            </div>
            <p className="mt-5 font-mono text-sm">
              {formatDateRange(overview)}
            </p>
            <p className="text-muted-foreground mt-2 text-xs">
              {formatNumber(overview.records)} 条记录 · {overview.projects}{' '}
              个项目
            </p>
          </article>
          <article className="rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
              <Clock3 className="size-4" />
              <span className="font-mono text-[11px] tracking-[0.16em] uppercase">
                最近同步
              </span>
            </div>
            <p className="mt-5 text-sm font-medium">
              {formatDate(overview.last_synced_at)}
            </p>
            <p className="text-muted-foreground mt-2 text-xs">
              数据更新后，工作台会使用最新快照。
            </p>
          </article>
          <article className="rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex items-center gap-2 text-sky-700 dark:text-sky-300">
              <Boxes className="size-4" />
              <span className="font-mono text-[11px] tracking-[0.16em] uppercase">
                最新版本
              </span>
            </div>
            <p className="mt-5 font-mono text-sm">{latestVersion}</p>
            <p className="text-muted-foreground mt-2 text-xs">
              版本线索将在 Release 数据同步后显示。
            </p>
          </article>
        </section>

        <section className="mt-8 grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="rounded-2xl border border-black/10 bg-white/70 p-6 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                  Project ledger
                </p>
                <h2 className="mt-2 text-xl font-semibold">已接入产品</h2>
              </div>
              <span className="text-muted-foreground font-mono text-xs">
                {formatNumber(projects.length)} / 03
              </span>
            </div>
            {projectsStatus === 'loading' && projects.length === 0 ? (
              <div
                className="text-muted-foreground mt-8 flex items-center gap-2 text-sm"
                role="status"
              >
                <Spinner size="small" />
                正在读取项目清单…
              </div>
            ) : projects.length === 0 ? (
              <p className="text-muted-foreground mt-8 text-sm">
                还没有可用的情报项目。
              </p>
            ) : (
              <ul className="mt-5 divide-y divide-black/10 dark:divide-white/10">
                {projects.map((project) => (
                  <li
                    key={project.id}
                    className="flex flex-col gap-3 py-4 first:pt-0 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <p className="text-foreground truncate font-medium">
                        {project.repository}
                      </p>
                      <p className="text-muted-foreground mt-1 font-mono text-[11px]">
                        {project.window_start} → {project.window_end}
                      </p>
                    </div>
                    <span
                      className={`w-fit rounded-full px-2.5 py-1 font-mono text-[11px] ${statusClass(project.status)}`}
                    >
                      {statusLabel(project.status)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-2xl border border-black/10 bg-[#20271f] p-6 text-[#eef2e8] dark:border-white/10 dark:bg-[#dfe7dc] dark:text-[#1c241c]">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-300 uppercase dark:text-emerald-800">
                  Topic signals
                </p>
                <h2 className="mt-2 text-xl font-semibold">主题热度</h2>
              </div>
              <Radar className="size-5 text-emerald-300 dark:text-emerald-800" />
            </div>
            {topics.length > 0 ? (
              <ul className="mt-5">
                {topics.map((topic) => (
                  <TopicSignal
                    key={`${topic.cluster_id}-${topic.month}`}
                    topic={topic}
                  />
                ))}
              </ul>
            ) : (
              <p className="mt-8 text-sm leading-6 text-white/65 dark:text-black/60">
                暂无主题信号。完成 Issue 同步后，系统会将聚类快照呈现在这里。
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
