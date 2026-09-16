import {
  CalendarDays,
  CircleAlert,
  CircleCheck,
  CircleX,
  Database,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react';

import { Button } from '../components/ui/button';
import { cn } from '../lib/utils';
import type {
  SourceType,
  SyncFailure,
  SyncFailureCategory,
  SyncRun,
  SyncRunCoverage,
  SyncRunStatus,
} from './types';

export type {
  SyncFailure,
  SyncFailureCategory,
  SyncRun,
  SyncRunCoverage,
  SyncRunStatus,
} from './types';

interface SyncStatusProps {
  run: SyncRun;
  onRetry?: () => void;
  retrying?: boolean;
  className?: string;
}

const SOURCE_TYPES: SourceType[] = [
  'documentation',
  'issue',
  'issue_comment',
  'release',
];

const SOURCE_LABELS: Record<SourceType, string> = {
  documentation: 'Documentation',
  issue: 'Issue',
  issue_comment: 'Issue comment',
  release: 'Release',
};

const STATUS_LABELS: Record<SyncRunStatus, string> = {
  queued: '排队中',
  running: '运行中',
  complete: '已完成',
  partial: '部分完成',
  failed: '同步失败',
};

const FAILURE_LABELS: Record<SyncFailureCategory, string> = {
  rate_limit: 'GitHub 请求受限',
  auth: '身份验证失败',
  not_found: '来源不存在',
  network: '网络暂时不可用',
  invalid_payload: '数据格式无法识别',
};

const STATUS_STYLES: Record<SyncRunStatus, string> = {
  queued:
    'border-slate-300/80 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-950/30 dark:text-slate-200',
  running:
    'border-sky-300/80 bg-sky-50 text-sky-700 dark:border-sky-700/70 dark:bg-sky-950/30 dark:text-sky-200',
  complete:
    'border-emerald-300/80 bg-emerald-50 text-emerald-700 dark:border-emerald-700/70 dark:bg-emerald-950/30 dark:text-emerald-200',
  partial:
    'border-amber-300/80 bg-amber-50 text-amber-800 dark:border-amber-700/70 dark:bg-amber-950/30 dark:text-amber-100',
  failed:
    'border-red-300/80 bg-red-50 text-red-700 dark:border-red-700/70 dark:bg-red-950/30 dark:text-red-200',
};

function statusIcon(status: SyncRunStatus) {
  if (status === 'running') return LoaderCircle;
  if (status === 'complete') return CircleCheck;
  if (status === 'partial') return CircleAlert;
  if (status === 'failed') return CircleX;
  return Database;
}

function formatCount(value: number | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(
    typeof value === 'number' && Number.isFinite(value) && value >= 0
      ? Math.floor(value)
      : 0,
  );
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '未记录';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '时间不可用';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed);
}

function formatDateRange(coverage: SyncRunCoverage): string {
  if (!coverage.date_from || !coverage.date_to) return '等待覆盖范围';
  return `${formatDate(coverage.date_from)} → ${formatDate(coverage.date_to)}`;
}

function sourceLabel(sourceType: string): string {
  if (sourceType in SOURCE_LABELS) {
    return SOURCE_LABELS[sourceType as SourceType];
  }
  return '数据来源';
}

function failureLabel(category: string): string {
  if (category in FAILURE_LABELS) {
    return FAILURE_LABELS[category as SyncFailureCategory];
  }
  return '同步服务暂时不可用';
}

function StatusIcon({ status }: { status: SyncRunStatus }) {
  const Icon = statusIcon(status);
  return (
    <Icon
      className={cn('size-4', status === 'running' && 'animate-spin')}
      aria-hidden="true"
    />
  );
}

function CountRow({
  sourceType,
  count,
}: {
  sourceType: SourceType;
  count: number | undefined;
}) {
  return (
    <li className="flex items-center justify-between border-b border-dashed border-black/10 py-2.5 last:border-0 dark:border-white/10">
      <span className="text-muted-foreground text-xs">
        {SOURCE_LABELS[sourceType]}
      </span>
      <span className="font-mono text-sm tabular-nums">
        {formatCount(count)}
      </span>
    </li>
  );
}

function FailureRow({ failure }: { failure: SyncFailure }) {
  return (
    <li className="flex items-start gap-2 border-b border-dashed border-red-200/80 py-2.5 last:border-0 dark:border-red-900/60">
      <CircleAlert
        className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-300"
        aria-hidden="true"
      />
      <div className="min-w-0 text-xs leading-5">
        <p className="font-medium text-red-800 dark:text-red-100">
          {sourceLabel(failure.source_type)} · {failureLabel(failure.category)}
        </p>
        <p className="text-red-700/75 dark:text-red-200/75">
          {failure.retryable ? '可以重试' : '需要先处理配置后再试'}
        </p>
      </div>
    </li>
  );
}

export default function SyncStatus({
  run,
  onRetry,
  retrying = false,
  className,
}: SyncStatusProps) {
  const retryAvailable =
    run.failures.some((failure) => failure.retryable) && Boolean(onRetry);
  const lastSuccess = run.coverage.last_synced_at ?? run.finished_at;

  return (
    <section
      className={cn(
        'rounded-2xl border border-black/10 bg-white/70 p-6 shadow-[0_14px_30px_-24px_rgba(30,40,30,0.65)] dark:border-white/10 dark:bg-white/[0.04]',
        className,
      )}
      aria-labelledby={`sync-status-${run.id}`}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
            Sync ledger
          </p>
          <h2
            id={`sync-status-${run.id}`}
            className="mt-2 text-xl font-semibold"
          >
            同步状态
          </h2>
        </div>
        <div
          className={cn(
            'inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium',
            STATUS_STYLES[run.status],
          )}
          role="status"
          aria-label={`同步状态：${STATUS_LABELS[run.status]}`}
        >
          <StatusIcon status={run.status} />
          {STATUS_LABELS[run.status]}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
        <div>
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
            <Database className="size-4" aria-hidden="true" />
            <span className="font-mono text-[11px] tracking-[0.16em] uppercase">
              Objects collected
            </span>
          </div>
          <ul className="mt-3">
            {SOURCE_TYPES.map((sourceType) => (
              <CountRow
                key={sourceType}
                sourceType={sourceType}
                count={run.counts[sourceType]}
              />
            ))}
          </ul>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-black/10 bg-black/[0.025] p-4 dark:border-white/10 dark:bg-white/[0.03]">
            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
              <CalendarDays className="size-4" aria-hidden="true" />
              <span className="font-mono text-[11px] tracking-[0.16em] uppercase">
                Actual coverage
              </span>
            </div>
            <p className="mt-3 text-sm font-medium">
              {formatDateRange(run.coverage)}
            </p>
            <p className="text-muted-foreground mt-1 text-xs">
              最近成功：{formatDate(lastSuccess)}
            </p>
            {run.coverage.repositories.length > 0 && (
              <p className="text-muted-foreground mt-1 truncate font-mono text-[11px]">
                {run.coverage.repositories.join(' · ')}
              </p>
            )}
            {run.coverage.capped && (
              <p className="mt-3 text-xs font-medium text-amber-800 dark:text-amber-200">
                已达到采集上限，当前结果只覆盖已采集范围。
              </p>
            )}
          </div>

          {run.started_at && (
            <p className="text-muted-foreground text-xs">
              开始于 {formatDate(run.started_at)}
              {run.finished_at
                ? ` · 结束于 ${formatDate(run.finished_at)}`
                : ''}
            </p>
          )}
        </div>
      </div>

      {run.failures.length > 0 && (
        <div className="mt-6 rounded-xl border border-red-200/80 bg-red-50/80 px-4 py-3 dark:border-red-900/60 dark:bg-red-950/20">
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm font-medium text-red-900 dark:text-red-100">
              {run.failures.length} 个来源需要关注
            </p>
            {retryAvailable && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onRetry}
                disabled={retrying}
                aria-label="重试失败项"
              >
                <RefreshCw
                  className={cn('size-4', retrying && 'animate-spin')}
                />
                {retrying ? '重试中…' : '重试失败项'}
              </Button>
            )}
          </div>
          <ul className="mt-2">
            {run.failures.map((failure, index) => (
              <FailureRow
                key={`${failure.source_type}-${failure.category}-${index}`}
                failure={failure}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
