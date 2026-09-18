import { CalendarDays, ExternalLink, FileText, GitBranch } from 'lucide-react';

import type { Evidence, SourceType } from './types';

const SOURCE_LABELS: Record<SourceType, string> = {
  documentation: '文档',
  issue: 'Issue',
  issue_comment: '评论',
  release: 'Release',
};

export interface EvidencePanelProps {
  evidence: Evidence[];
  evidenceIds?: string[];
  heading?: string;
  id?: string;
}

export function formatEvidenceDate(value: string | null): string {
  if (!value) return '日期未记录';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '日期未记录';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(
    parsed,
  );
}

function EvidenceSourceCard({ source }: { source: Evidence }) {
  return (
    <article className="rounded-xl border border-black/10 bg-white/70 p-4 dark:border-white/10 dark:bg-white/[0.04]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-600/10 px-2 py-1 font-mono text-emerald-800 dark:text-emerald-200">
          <FileText className="size-3" />
          {SOURCE_LABELS[source.source_type]}
        </span>
        <span className="inline-flex items-center gap-1 font-mono text-[#566057] dark:text-[#b9c4b8]">
          <GitBranch className="size-3" />
          {source.repository}
        </span>
        <span className="inline-flex items-center gap-1 text-[#697267] dark:text-[#aeb8ac]">
          <CalendarDays className="size-3" />
          {formatEvidenceDate(source.occurred_at)}
        </span>
      </div>

      <h4 className="mt-3 text-sm leading-5 font-semibold text-[#20241f] dark:text-[#f2f3e9]">
        {source.title || '未命名来源'}
      </h4>
      <p className="mt-2 text-sm leading-6 text-[#566057] dark:text-[#c5cdc2]">
        {source.excerpt || '该来源没有摘要。'}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        {source.author && (
          <span className="text-[#697267] dark:text-[#aeb8ac]">
            作者 · {source.author}
          </span>
        )}
        <a
          href={source.source_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-medium text-[#1f6b4d] underline-offset-4 transition-colors hover:text-[#18563e] hover:underline dark:text-emerald-300 dark:hover:text-emerald-200"
        >
          在 GitHub 中打开
          <ExternalLink className="size-3.5" />
        </a>
      </div>
    </article>
  );
}

export default function EvidencePanel({
  evidence,
  evidenceIds,
  heading = '证据来源',
  id,
}: EvidencePanelProps) {
  const evidenceById = new Map(evidence.map((source) => [source.id, source]));
  const requestedIds = evidenceIds ?? evidence.map((source) => source.id);
  const sources = requestedIds
    .map((evidenceId) => evidenceById.get(evidenceId))
    .filter((source): source is Evidence => Boolean(source));
  const resolvedIds = new Set(sources.map((source) => source.id));
  const missingEvidenceIds = requestedIds.filter(
    (evidenceId) => !resolvedIds.has(evidenceId),
  );

  return (
    <div
      id={id}
      className="mt-4 border-t border-dashed border-black/10 pt-4 dark:border-white/10"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-xs font-semibold tracking-wide text-[#39453a] dark:text-[#d6ded2]">
          {heading}
        </h3>
        <span className="font-mono text-[10px] text-[#697267] dark:text-[#aeb8ac]">
          {sources.length} / {requestedIds.length} 已解析
        </span>
      </div>

      {sources.length ? (
        <div className="mt-3 space-y-3">
          {sources.map((source, sourceIndex) => (
            <EvidenceSourceCard
              key={`${source.id}-${sourceIndex}`}
              source={source}
            />
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-dashed border-amber-300/70 bg-amber-50/70 px-3 py-3 text-xs leading-5 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-100">
          当前响应没有返回可打开的来源详情。
        </p>
      )}

      {missingEvidenceIds.length > 0 && (
        <div className="mt-3 rounded-lg border border-dashed border-black/10 px-3 py-3 text-xs leading-5 text-[#697267] dark:border-white/10 dark:text-[#aeb8ac]">
          <p>以下证据仅返回了稳定标识，详情暂未随响应返回：</p>
          <ul className="mt-1 space-y-1 font-mono">
            {missingEvidenceIds.map((evidenceId, evidenceIndex) => (
              <li key={`${evidenceId}-${evidenceIndex}`}>· {evidenceId}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
