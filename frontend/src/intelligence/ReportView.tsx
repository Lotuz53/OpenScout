import { CircleAlert, Download, ExternalLink, FileText } from 'lucide-react';

import { baseURL } from '../api/client';
import endpoints from '../api/endpoints';
import { Button } from '../components/ui/button';
import type { ReportDocument, ReportSection, ReportSource } from './types';

export const REPORT_SECTION_HEADINGS = [
  '执行摘要',
  '功能对比',
  '反馈趋势',
  '产品机会线索',
  '风险与证据限制',
  '完整来源',
] as const;

export type ReportDownloadFormat = 'markdown' | 'pdf';

export interface ReportViewProps {
  report: ReportDocument;
  onDownload?: (format: ReportDownloadFormat) => void | Promise<void>;
  downloadingFormat?: ReportDownloadFormat | null;
  downloadError?: string | null;
}

function sectionContent(section: ReportSection | undefined): {
  paragraphs: string[];
  bullets: string[];
} {
  return {
    paragraphs: section?.paragraphs ?? [],
    bullets: section?.bullets ?? [],
  };
}

function ReportSourceRow({ source }: { source: ReportSource }) {
  return (
    <li className="rounded-xl border border-black/10 bg-white/65 px-4 py-3 dark:border-white/10 dark:bg-white/[0.035]">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#697267] dark:text-[#aeb8ac]">
        <span className="font-mono">{source.id}</span>
        <span>·</span>
        <span>{source.repository}</span>
        <span>·</span>
        <span>{source.source_type}</span>
      </div>
      <a
        href={source.url}
        target="_blank"
        rel="noreferrer"
        className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[#1f6b4d] underline-offset-4 hover:text-[#18563e] hover:underline dark:text-emerald-300 dark:hover:text-emerald-200"
      >
        {source.title || '未命名来源'}
        <ExternalLink className="size-3.5" />
      </a>
      {source.excerpt && (
        <p className="mt-1 text-xs leading-5 text-[#566057] dark:text-[#c5cdc2]">
          {source.excerpt}
        </p>
      )}
    </li>
  );
}

function DownloadButton({
  format,
  reportId,
  onDownload,
  downloadingFormat,
}: {
  format: ReportDownloadFormat;
  reportId: string | null;
  onDownload?: (format: ReportDownloadFormat) => void | Promise<void>;
  downloadingFormat?: ReportDownloadFormat | null;
}) {
  const label = format === 'markdown' ? '下载 Markdown' : '下载 PDF';
  const isDownloading = downloadingFormat === format;

  if (!onDownload && reportId) {
    return (
      <Button asChild variant="outline" size="sm" className="rounded-full">
        <a
          href={`${baseURL}${endpoints.INTELLIGENCE.REPORT_DOWNLOAD(reportId, format)}`}
          download
        >
          <Download className="size-3.5" />
          {label}
        </a>
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={!onDownload || isDownloading || !reportId}
      onClick={() => {
        if (onDownload) void onDownload(format);
      }}
      className="rounded-full"
    >
      <Download className="size-3.5" />
      {isDownloading ? '准备下载…' : label}
    </Button>
  );
}

export default function ReportView({
  report,
  onDownload,
  downloadingFormat = null,
  downloadError = null,
}: ReportViewProps) {
  const sectionsByHeading = new Map(
    report.sections.map((section) => [section.heading, section]),
  );

  return (
    <section
      aria-labelledby="report-view-title"
      className="rounded-2xl border border-black/10 bg-[#fbfaf5] p-6 shadow-[0_20px_45px_-36px_rgba(30,40,30,0.9)] dark:border-white/10 dark:bg-[#171d17]"
    >
      <div className="flex flex-col gap-4 border-b border-black/10 pb-5 sm:flex-row sm:items-start sm:justify-between dark:border-white/10">
        <div>
          <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.18em] text-[#1f6b4d] uppercase dark:text-emerald-300">
            <FileText className="size-4" />
            Saved report
          </p>
          <h2 id="report-view-title" className="mt-2 text-xl font-semibold">
            {report.title}
          </h2>
          <p className="mt-2 text-xs leading-5 text-[#697267] dark:text-[#aeb8ac]">
            报告基于当前已返回的结构化结果生成，不会重新执行检索。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <DownloadButton
            format="markdown"
            reportId={report.id}
            onDownload={onDownload}
            downloadingFormat={downloadingFormat}
          />
          <DownloadButton
            format="pdf"
            reportId={report.id}
            onDownload={onDownload}
            downloadingFormat={downloadingFormat}
          />
        </div>
      </div>

      {downloadError && (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-red-300/70 bg-red-50 px-3 py-3 text-xs leading-5 text-red-800 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-100">
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          <span>{downloadError}</span>
        </div>
      )}

      <div className="mt-6 space-y-5">
        {REPORT_SECTION_HEADINGS.map((heading, index) => {
          const content = sectionContent(sectionsByHeading.get(heading));
          return (
            <section
              key={heading}
              aria-labelledby={`report-section-${index}`}
              className="rounded-xl border border-black/10 bg-white/60 p-4 dark:border-white/10 dark:bg-white/[0.025]"
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-[10px] text-[#1f6b4d] dark:text-emerald-300">
                  0{index + 1}
                </span>
                <h3
                  id={`report-section-${index}`}
                  className="text-sm font-semibold text-[#20241f] dark:text-[#f2f3e9]"
                >
                  {heading}
                </h3>
              </div>

              <div className="mt-3 space-y-2 text-sm leading-6 text-[#566057] dark:text-[#c5cdc2]">
                {content.paragraphs.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
                {content.bullets.length > 0 && (
                  <ul className="list-inside list-disc space-y-1">
                    {content.bullets.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                )}
                {!content.paragraphs.length && !content.bullets.length && (
                  <p className="text-[#697267] dark:text-[#aeb8ac]">
                    暂无内容。
                  </p>
                )}
              </div>

              {heading === '完整来源' && report.sources.length > 0 && (
                <ul className="mt-4 space-y-2">
                  {report.sources.map((source) => (
                    <ReportSourceRow key={source.id} source={source} />
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}
