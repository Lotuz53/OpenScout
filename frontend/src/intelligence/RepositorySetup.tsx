import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CircleAlert,
  FileText,
  GitBranch,
  Loader2,
  MessageSquareText,
  PackageCheck,
  ShieldCheck,
} from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { useSelector } from 'react-redux';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { selectToken } from '../preferences/preferenceSlice';
import intelligenceService from './intelligenceService';
import type { IntelligenceProject, RepositoryPreflight } from './types';

const DEFAULT_WINDOW_START = '2025-09-14';
const DEFAULT_WINDOW_END = '2026-09-14';

const PREFLIGHT_ERROR_MESSAGES: Record<string, string> = {
  invalid_repository: '请输入有效的 GitHub 公共仓库地址。',
  not_found: '找不到该 GitHub 仓库，请检查地址是否正确。',
  private_not_supported: '当前阶段只支持公开 GitHub 仓库。',
  github_unavailable: '暂时无法读取该 GitHub 仓库，请稍后重试。',
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function formatNumber(value: number | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(value ?? 0);
}

function preflightErrorMessage(preflight: RepositoryPreflight): string {
  return (
    preflight.message ??
    (preflight.error_code
      ? PREFLIGHT_ERROR_MESSAGES[preflight.error_code]
      : undefined) ??
    '该仓库暂时无法接入。'
  );
}

function isConfirmationWarning(preflight: RepositoryPreflight): boolean {
  return (
    preflight.archived ||
    preflight.warnings.some((warning) => warning.includes('上限'))
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number | undefined;
  icon: typeof FileText;
}) {
  return (
    <div className="rounded-xl border border-black/10 bg-black/[0.025] p-4 dark:border-white/10 dark:bg-white/[0.04]">
      <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
        <Icon className="size-4" />
        <span className="text-muted-foreground text-xs">{label}</span>
      </div>
      <p className="mt-3 font-mono text-2xl tabular-nums">
        {formatNumber(value)}
      </p>
    </div>
  );
}

export default function RepositorySetup() {
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const [repository, setRepository] = useState('');
  const [windowStart, setWindowStart] = useState(DEFAULT_WINDOW_START);
  const [windowEnd, setWindowEnd] = useState(DEFAULT_WINDOW_END);
  const [preflight, setPreflight] = useState<RepositoryPreflight | null>(null);
  const [preflightStatus, setPreflightStatus] = useState<'idle' | 'loading'>(
    'idle',
  );
  const [createStatus, setCreateStatus] = useState<'idle' | 'loading'>('idle');
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dateError = windowStart && windowEnd && windowEnd < windowStart;
  const hasPreflightError = Boolean(preflight?.error_code);
  const requiresConfirmation = Boolean(
    preflight && !hasPreflightError && isConfirmationWarning(preflight),
  );
  const canCreate = Boolean(
    preflight &&
    !hasPreflightError &&
    !dateError &&
    (!requiresConfirmation || confirmed),
  );

  const handlePreflight = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = repository.trim();
    if (!value || dateError) return;

    setError(null);
    setPreflight(null);
    setConfirmed(false);
    setPreflightStatus('loading');
    try {
      setPreflight(await intelligenceService.preflight(value, token));
    } catch (requestError) {
      setError(errorMessage(requestError, '无法检查该 GitHub 仓库。'));
    } finally {
      setPreflightStatus('idle');
    }
  };

  const handleCreate = async () => {
    if (!preflight || !canCreate) return;

    setError(null);
    setCreateStatus('loading');
    try {
      const project: IntelligenceProject =
        await intelligenceService.createProject({
          repository: preflight.repository,
          window_start: windowStart,
          window_end: windowEnd,
          token,
        });
      await intelligenceService.syncProject(project.id, token);
      navigate('/intelligence');
    } catch (requestError) {
      setError(errorMessage(requestError, '无法创建项目或开始同步。'));
    } finally {
      setCreateStatus('idle');
    }
  };

  return (
    <div className="min-h-full bg-[#f6f4ed] px-5 py-8 text-[#20241f] md:px-10 md:py-10 lg:px-14 dark:bg-[#111511] dark:text-[#f2f3e9]">
      <div className="mx-auto max-w-5xl">
        <Link
          to="/intelligence"
          className="text-muted-foreground inline-flex items-center gap-2 text-xs transition-colors hover:text-emerald-700 dark:hover:text-emerald-300"
        >
          <ArrowLeft className="size-4" />
          返回产品情报
        </Link>

        <header className="mt-8 max-w-3xl">
          <div className="mb-4 flex items-center gap-2 font-mono text-[11px] tracking-[0.22em] text-emerald-700 uppercase dark:text-emerald-300">
            <GitBranch className="size-4" />
            OpenScout / repository intake
          </div>
          <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
            接入一个公开仓库
          </h1>
          <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-6">
            先读取 GitHub
            的公开元数据与数量估算，再决定是否创建项目。预检不会下载仓库正文。
          </p>
        </header>

        <section className="mt-8 grid gap-6 lg:grid-cols-[0.75fr_1.25fr]">
          <aside className="rounded-2xl bg-[#20271f] p-6 text-[#eef2e8] dark:bg-[#dfe7dc] dark:text-[#1c241c]">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-300 uppercase dark:text-emerald-800">
                  Before indexing
                </p>
                <h2 className="mt-2 text-xl font-semibold">先看清范围</h2>
              </div>
              <ShieldCheck className="size-5 text-emerald-300 dark:text-emerald-800" />
            </div>
            <ul className="mt-7 space-y-4 text-sm leading-6 text-white/70 dark:text-black/65">
              <li className="flex gap-3">
                <Check className="mt-1 size-4 shrink-0 text-emerald-300 dark:text-emerald-800" />
                只接入公开 GitHub 仓库，不需要授予写入权限。
              </li>
              <li className="flex gap-3">
                <Check className="mt-1 size-4 shrink-0 text-emerald-300 dark:text-emerald-800" />
                Issue、Release 和可索引文档会分别显示预估数量。
              </li>
              <li className="flex gap-3">
                <Check className="mt-1 size-4 shrink-0 text-emerald-300 dark:text-emerald-800" />
                创建后会立即排队首次同步，完成情况可在产品情报中查看。
              </li>
            </ul>
          </aside>

          <form
            onSubmit={handlePreflight}
            className="rounded-2xl border border-black/10 bg-white/70 p-6 shadow-[0_14px_30px_-24px_rgba(30,40,30,0.65)] dark:border-white/10 dark:bg-white/[0.04]"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                  Repository details
                </p>
                <h2 className="mt-2 text-xl font-semibold">设置研究窗口</h2>
              </div>
              <CalendarDays className="text-muted-foreground size-5" />
            </div>

            <div className="mt-7">
              <Input
                id="repository"
                label="GitHub 仓库地址"
                value={repository}
                onChange={(event) => {
                  setRepository(event.target.value);
                  setPreflight(null);
                  setError(null);
                }}
                placeholder="https://github.com/owner/repository"
                leftIcon={
                  <GitBranch className="text-muted-foreground size-4" />
                }
                autoComplete="url"
                required
              />
              <p className="text-muted-foreground mt-2 text-xs">
                支持 GitHub URL 或 owner/name 格式。
              </p>
            </div>

            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <label className="text-muted-foreground block text-xs">
                开始日期
                <input
                  type="date"
                  aria-label="开始日期"
                  value={windowStart}
                  onChange={(event) => setWindowStart(event.target.value)}
                  className="border-border bg-background text-foreground mt-1 h-10 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/30"
                />
              </label>
              <label className="text-muted-foreground block text-xs">
                结束日期
                <input
                  type="date"
                  aria-label="结束日期"
                  value={windowEnd}
                  onChange={(event) => setWindowEnd(event.target.value)}
                  className="border-border bg-background text-foreground mt-1 h-10 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/30"
                />
              </label>
            </div>
            {dateError && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-300">
                结束日期不能早于开始日期。
              </p>
            )}

            <div className="mt-7 flex justify-end">
              <Button
                type="submit"
                disabled={
                  !repository.trim() ||
                  Boolean(dateError) ||
                  preflightStatus === 'loading'
                }
                className="rounded-full px-5"
              >
                {preflightStatus === 'loading' ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ArrowRight className="size-4" />
                )}
                检查仓库
              </Button>
            </div>
          </form>
        </section>

        {error && (
          <div className="mt-6">
            <div className="flex items-start gap-3 rounded-xl border border-red-300/80 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-700/60 dark:bg-red-950/30 dark:text-red-100">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />
              <p>{error}</p>
            </div>
          </div>
        )}

        {preflight?.error_code && (
          <div className="mt-6">
            <div className="flex items-start gap-3 rounded-xl border border-red-300/80 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-700/60 dark:bg-red-950/30 dark:text-red-100">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />
              <div>
                <p className="font-medium">无法创建项目</p>
                <p className="mt-1">{preflightErrorMessage(preflight)}</p>
              </div>
            </div>
          </div>
        )}

        {preflight && !preflight.error_code && (
          <section className="mt-6 rounded-2xl border border-black/10 bg-white/70 p-6 dark:border-white/10 dark:bg-white/[0.04]">
            <div className="flex flex-col gap-3 border-b border-dashed border-black/10 pb-5 sm:flex-row sm:items-end sm:justify-between dark:border-white/10">
              <div>
                <p className="font-mono text-[11px] tracking-[0.18em] text-emerald-700 uppercase dark:text-emerald-300">
                  Preflight result
                </p>
                <h2 className="mt-2 text-xl font-semibold">
                  {preflight.repository}
                </h2>
              </div>
              <span className="text-muted-foreground font-mono text-xs">
                默认分支：{preflight.default_branch ?? 'main'}
              </span>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <StatCard
                label="Issues"
                value={preflight.estimated_counts.issues}
                icon={MessageSquareText}
              />
              <StatCard
                label="Releases"
                value={preflight.estimated_counts.releases}
                icon={PackageCheck}
              />
              <StatCard
                label="可索引文档"
                value={preflight.estimated_counts.documents}
                icon={FileText}
              />
            </div>

            {(preflight.archived || preflight.warnings.length > 0) && (
              <div className="mt-5 space-y-2">
                {preflight.archived &&
                !preflight.warnings.some((warning) =>
                  warning.includes('归档'),
                ) ? (
                  <p className="text-muted-foreground text-sm">
                    该仓库已归档，数据可能不会继续更新。
                  </p>
                ) : null}
                {preflight.warnings.map((warning) => (
                  <div
                    key={warning}
                    className="flex items-start gap-3 rounded-xl border border-amber-300/80 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-100"
                  >
                    <CircleAlert className="mt-0.5 size-4 shrink-0" />
                    <p>{warning}</p>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-6 flex flex-col gap-4 border-t border-dashed border-black/10 pt-5 dark:border-white/10">
              {requiresConfirmation && (
                <label className="flex cursor-pointer items-start gap-3 text-sm leading-6">
                  <input
                    type="checkbox"
                    aria-label="确认仓库范围警告"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                    className="mt-1 size-4 accent-emerald-600"
                  />
                  <span>
                    我已了解以上范围提示，仍要按当前采集上限创建项目。
                  </span>
                </label>
              )}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-muted-foreground text-xs">
                  研究窗口：{windowStart} → {windowEnd}
                </p>
                <Button
                  type="button"
                  disabled={!canCreate || createStatus === 'loading'}
                  onClick={handleCreate}
                  className="rounded-full px-5"
                >
                  {createStatus === 'loading' ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <ArrowRight className="size-4" />
                  )}
                  创建项目并开始同步
                </Button>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
