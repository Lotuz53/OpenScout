import {
  CalendarDays,
  CircleAlert,
  ExternalLink,
  FileText,
  Globe2,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { Button } from '../components/ui/button';
import intelligenceService from './intelligenceService';
import type { SharedReport, SharedReportSection } from './types';

function formatDate(value: string | null): string {
  if (!value) return '未记录';
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

function formatDateRange(report: SharedReport): string {
  const { date_from: dateFrom, date_to: dateTo } = report.coverage;
  if (!dateFrom || !dateTo) return '覆盖范围未记录';
  return `${formatDate(dateFrom)} → ${formatDate(dateTo)}`;
}

function Section({
  section,
  index,
}: {
  section: SharedReportSection;
  index: number;
}) {
  return (
    <section
      aria-labelledby={`shared-report-section-${index}`}
      className="border-t border-black/10 pt-5 first:border-t-0 first:pt-0 dark:border-white/10"
    >
      <div className="flex items-start gap-3">
        <span className="pt-0.5 font-mono text-[10px] tracking-[0.12em] text-[#1f6b4d] dark:text-emerald-300">
          {String(index + 1).padStart(2, '0')}
        </span>
        <h2
          id={`shared-report-section-${index}`}
          className="text-lg font-semibold text-[#20241f] dark:text-[#f2f3e9]"
        >
          {section.heading || '未命名章节'}
        </h2>
      </div>
      <div className="mt-3 space-y-2 pl-7 text-sm leading-6 text-[#566057] dark:text-[#c5cdc2]">
        {section.paragraphs.map((paragraph, paragraphIndex) => (
          <p key={`${paragraph}-${paragraphIndex}`}>{paragraph}</p>
        ))}
        {section.bullets.length > 0 && (
          <ul className="list-inside list-disc space-y-1">
            {section.bullets.map((bullet, bulletIndex) => (
              <li key={`${bullet}-${bulletIndex}`}>{bullet}</li>
            ))}
          </ul>
        )}
        {!section.paragraphs.length && !section.bullets.length && (
          <p className="text-[#697267] dark:text-[#aeb8ac]">暂无内容。</p>
        )}
      </div>
    </section>
  );
}

function SharedReportContent({ report }: { report: SharedReport }) {
  return (
    <main className="min-h-screen bg-[#f6f4ed] px-5 py-8 text-[#20241f] md:px-10 md:py-12 dark:bg-[#111511] dark:text-[#f2f3e9]">
      <div className="mx-auto max-w-5xl">
        <header className="border-b border-black/10 pb-8 dark:border-white/10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.2em] text-[#1f6b4d] uppercase dark:text-emerald-300">
              <FileText className="size-4" aria-hidden="true" />
              OpenScout / shared field note
            </p>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-700/20 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800 dark:border-emerald-300/20 dark:bg-emerald-950/30 dark:text-emerald-200">
              <ShieldCheck className="size-3.5" aria-hidden="true" />
              只读公开报告
            </span>
          </div>
          <h1 className="mt-6 max-w-3xl text-3xl font-semibold tracking-tight md:text-4xl">
            {report.title}
          </h1>
          <p className="mt-3 flex items-center gap-2 text-sm text-[#697267] dark:text-[#aeb8ac]">
            <CalendarDays className="size-4" aria-hidden="true" />
            生成于 {formatDate(report.created_at)}
          </p>
        </header>

        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <article className="space-y-6 rounded-2xl border border-black/10 bg-[#fbfaf5] p-6 shadow-[0_20px_45px_-36px_rgba(30,40,30,0.9)] md:p-8 dark:border-white/10 dark:bg-[#171d17]">
            <div className="flex items-center gap-2 border-b border-black/10 pb-4 font-mono text-[11px] tracking-[0.16em] text-[#1f6b4d] uppercase dark:border-white/10 dark:text-emerald-300">
              <Globe2 className="size-4" aria-hidden="true" />
              Intelligence report
            </div>
            {report.sections.map((section, index) => (
              <Section
                key={`${section.heading}-${index}`}
                section={section}
                index={index}
              />
            ))}
          </article>

          <aside className="h-fit space-y-5 lg:sticky lg:top-8">
            <section className="rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
              <p className="font-mono text-[10px] tracking-[0.16em] text-[#1f6b4d] uppercase dark:text-emerald-300">
                Coverage
              </p>
              <p className="mt-3 text-sm leading-6 text-[#566057] dark:text-[#c5cdc2]">
                {formatDateRange(report)}
              </p>
              {report.coverage.repositories.length > 0 && (
                <ul className="mt-4 space-y-2 border-t border-dashed border-black/10 pt-4 text-xs text-[#697267] dark:border-white/10 dark:text-[#aeb8ac]">
                  {report.coverage.repositories.map((repository) => (
                    <li key={repository} className="font-mono">
                      {repository}
                    </li>
                  ))}
                </ul>
              )}
              {report.coverage.capped && (
                <p className="mt-4 border-t border-dashed border-amber-300/70 pt-3 text-xs leading-5 text-amber-800 dark:border-amber-700/70 dark:text-amber-200">
                  本报告覆盖的数据达到采集上限。
                </p>
              )}
            </section>

            {report.sources.length > 0 && (
              <section className="rounded-2xl border border-black/10 bg-white/70 p-5 dark:border-white/10 dark:bg-white/[0.04]">
                <p className="font-mono text-[10px] tracking-[0.16em] text-[#1f6b4d] uppercase dark:text-emerald-300">
                  Sources
                </p>
                <ul className="mt-4 space-y-3">
                  {report.sources.map((source, index) => (
                    <li key={`${source.url}-${index}`}>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-start gap-1 text-sm leading-5 text-[#1f6b4d] underline-offset-4 hover:underline dark:text-emerald-300"
                      >
                        <span>{source.title || '未命名来源'}</span>
                        <ExternalLink
                          className="mt-0.5 size-3.5 shrink-0"
                          aria-hidden="true"
                        />
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>

        <footer className="mt-8 border-t border-black/10 pt-5 text-xs leading-5 text-[#697267] dark:border-white/10 dark:text-[#aeb8ac]">
          这是只读分享链接。报告内容和来源范围由发布者在生成时确定。
        </footer>
      </div>
    </main>
  );
}

export default function SharedReportView() {
  const { token } = useParams<{ token: string }>();
  const [report, setReport] = useState<SharedReport | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError(false);
    if (!token) {
      setError(true);
      return () => {
        cancelled = true;
      };
    }

    void intelligenceService
      .getSharedReport(token)
      .then((result) => {
        if (!cancelled) setReport(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f6f4ed] px-6 text-[#20241f] dark:bg-[#111511] dark:text-[#f2f3e9]">
        <section className="max-w-md rounded-2xl border border-red-300/70 bg-red-50 p-6 text-center dark:border-red-800/60 dark:bg-red-950/30">
          <CircleAlert
            className="mx-auto size-6 text-red-700 dark:text-red-300"
            aria-hidden="true"
          />
          <h1 className="mt-3 text-lg font-semibold">共享报告不可用</h1>
          <p className="mt-2 text-sm leading-6 text-red-800 dark:text-red-100">
            链接可能已失效、被撤销，或报告暂时无法读取。
          </p>
          <Button asChild variant="outline" className="mt-5 rounded-full">
            <a href="/">返回首页</a>
          </Button>
        </section>
      </main>
    );
  }

  if (!report) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f6f4ed] px-6 text-sm text-[#697267] dark:bg-[#111511] dark:text-[#aeb8ac]">
        正在打开共享报告…
      </main>
    );
  }

  return <SharedReportContent report={report} />;
}
