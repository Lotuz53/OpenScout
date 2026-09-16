import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import ReportView from './ReportView';

const report = {
  id: 'report-1',
  title: 'OpenScout AI 产品情报报告',
  user_id: 'user-1',
  project_ids: ['project-1'],
  sections: [
    { heading: '完整来源', paragraphs: ['来源列表'], bullets: [] },
    { heading: '执行摘要', paragraphs: ['摘要'], bullets: [] },
  ],
  sources: [],
  source_ids: [],
  created_at: '2026-03-01T00:00:00Z',
};

describe('report view', () => {
  it('keeps the six report sections in the fixed reading order', () => {
    const markup = renderToStaticMarkup(
      <ReportView report={report} onDownload={vi.fn()} />,
    );

    const sectionOrder = [
      '执行摘要',
      '功能对比',
      '反馈趋势',
      '产品机会线索',
      '风险与证据限制',
      '完整来源',
    ];
    const positions = sectionOrder.map((heading) => markup.indexOf(heading));

    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual(
      [...positions].sort((left, right) => left - right),
    );
    expect(markup).toContain('下载 Markdown');
    expect(markup).toContain('下载 PDF');
  });
});
