import { ChevronDown, CircleAlert, GitCompareArrows } from 'lucide-react';

import EvidencePanel, { formatEvidenceDate } from './EvidencePanel';
import type { ComparisonCell, ComparisonRow, Evidence } from './types';

const EMPTY_EVIDENCE: Evidence[] = [];

const STATUS_LABELS: Record<ComparisonCell['status'], string> = {
  supported: '已支持',
  not_supported: '不支持',
  unknown: '尚未确认',
};

const DIMENSION_LABELS: Record<string, string> = {
  enterprise_sso: '企业单点登录',
};

export interface ComparisonMatrixProps {
  rows: ComparisonRow[];
  evidence?: Evidence[];
}

function dimensionLabel(dimension: string): string {
  return (
    DIMENSION_LABELS[dimension] ??
    dimension
      .replace(/[_-]+/g, ' ')
      .replace(/^\w/, (value) => value.toUpperCase())
  );
}

function repositoriesForRows(rows: ComparisonRow[]): string[] {
  const repositories: string[] = [];
  rows.forEach((row) => {
    Object.keys(row.cells).forEach((repository) => {
      if (!repositories.includes(repository)) repositories.push(repository);
    });
  });
  return repositories;
}

function unknownCell(): ComparisonCell {
  return {
    status: 'unknown',
    display_label: '尚未确认',
    first_evidence_date: null,
    community_signal_count: 0,
    evidence_ids: [],
    coverage_warning: null,
  };
}

function statusStyle(status: ComparisonCell['status']): string {
  return {
    supported:
      'border-emerald-300/70 bg-emerald-50/70 text-emerald-900 dark:border-emerald-700/60 dark:bg-emerald-950/20 dark:text-emerald-100',
    not_supported:
      'border-rose-300/70 bg-rose-50/70 text-rose-900 dark:border-rose-700/60 dark:bg-rose-950/20 dark:text-rose-100',
    unknown:
      'border-amber-300/70 bg-amber-50/70 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-100',
  }[status];
}

function ComparisonCellView({
  cell,
  evidence,
  repository,
}: {
  cell: ComparisonCell;
  evidence: Evidence[];
  repository: string;
}) {
  const label =
    cell.status === 'unknown'
      ? STATUS_LABELS.unknown
      : cell.display_label || STATUS_LABELS[cell.status];

  return (
    <div
      className={`min-w-52 rounded-xl border p-3 ${statusStyle(cell.status)}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{label}</span>
        {cell.status === 'unknown' && <CircleAlert className="size-4" />}
      </div>
      <dl className="mt-3 space-y-1.5 text-[11px]">
        <div className="flex items-center justify-between gap-2">
          <dt className="opacity-70">首个证据</dt>
          <dd className="font-mono">
            {formatEvidenceDate(cell.first_evidence_date)}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="opacity-70">社区信号</dt>
          <dd className="font-mono">{cell.community_signal_count}</dd>
        </div>
      </dl>

      {cell.coverage_warning && (
        <p className="mt-3 border-t border-current/15 pt-2 text-[11px] leading-5 opacity-80">
          {cell.coverage_warning}
        </p>
      )}

      <details className="group mt-3 border-t border-current/15 pt-2">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-[11px] font-medium [&::-webkit-details-marker]:hidden">
          <span>
            {cell.evidence_ids.length
              ? `查看 ${cell.evidence_ids.length} 条来源`
              : '暂无可展开来源'}
          </span>
          <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
        </summary>
        {cell.evidence_ids.length ? (
          <EvidencePanel
            evidence={evidence}
            evidenceIds={cell.evidence_ids}
            heading={`${repository} / 来源`}
          />
        ) : (
          <p className="pt-3 text-[11px] leading-5 opacity-70">
            该单元格没有可引用的证据标识。
          </p>
        )}
      </details>
    </div>
  );
}

export default function ComparisonMatrix({
  rows,
  evidence = EMPTY_EVIDENCE,
}: ComparisonMatrixProps) {
  const repositories = repositoriesForRows(rows);

  if (!rows.length || !repositories.length) {
    return (
      <div className="rounded-xl border border-dashed border-black/15 px-4 py-8 text-center text-sm text-[#697267] dark:border-white/15 dark:text-[#aeb8ac]">
        暂无可比较的产品或功能维度。
      </div>
    );
  }

  return (
    <section aria-labelledby="comparison-matrix-title">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.18em] text-[#1f6b4d] uppercase dark:text-emerald-300">
            <GitCompareArrows className="size-4" />
            Evidence matrix
          </p>
          <h3
            id="comparison-matrix-title"
            className="mt-2 text-lg font-semibold"
          >
            产品能力对比
          </h3>
        </div>
        <span className="font-mono text-xs text-[#697267] dark:text-[#aeb8ac]">
          {rows.length} 个维度
        </span>
      </div>

      <div className="mt-5 overflow-x-auto rounded-2xl border border-black/10 dark:border-white/10">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <thead className="bg-black/[0.035] dark:bg-white/[0.04]">
            <tr>
              <th className="w-44 px-4 py-3 font-mono text-[10px] tracking-[0.12em] text-[#697267] uppercase dark:text-[#aeb8ac]">
                功能维度
              </th>
              {repositories.map((repository) => (
                <th
                  key={repository}
                  className="px-4 py-3 font-mono text-[10px] tracking-[0.08em] text-[#697267] uppercase dark:text-[#aeb8ac]"
                >
                  {repository}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.dimension}
                className="border-t border-black/10 align-top dark:border-white/10"
              >
                <th className="px-4 py-4 text-sm font-semibold text-[#20241f] dark:text-[#f2f3e9]">
                  {dimensionLabel(row.dimension)}
                </th>
                {repositories.map((repository) => (
                  <td key={repository} className="px-4 py-4">
                    <ComparisonCellView
                      cell={row.cells[repository] ?? unknownCell()}
                      evidence={evidence}
                      repository={repository}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
