import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
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

  it('shows owner controls for creating, copying, and revoking a share link', () => {
    const createMarkup = renderToStaticMarkup(
      <ReportView report={report} onCreateShare={vi.fn()} />,
    );
    const activeMarkup = renderToStaticMarkup(
      <ReportView
        report={report}
        share={{
          token: 'share-token',
          path: '/reports/shared/share-token',
          shared_at: '2026-03-01T00:00:00Z',
        }}
        onCopyShare={vi.fn()}
        onRevokeShare={vi.fn()}
      />,
    );

    expect(createMarkup).toContain('生成分享链接');
    expect(activeMarkup).toContain('/reports/shared/share-token');
    expect(activeMarkup).toContain('复制链接');
    expect(activeMarkup).toContain('撤销链接');
  });

  it('does not emit duplicate-key warnings for repeated report content', () => {
    const duplicateReport = {
      ...report,
      sections: [
        {
          heading: '执行摘要',
          paragraphs: ['重复段落', '重复段落'],
          bullets: ['重复条目', '重复条目'],
        },
        ...report.sections,
      ],
      sources: [
        {
          id: 'source-1',
          title: '重复来源',
          url: 'https://example.com/one',
          repository: 'owner/repo',
          source_type: 'issue',
          excerpt: '',
        },
        {
          id: 'source-1',
          title: '重复来源',
          url: 'https://example.com/two',
          repository: 'owner/repo',
          source_type: 'issue',
          excerpt: '',
        },
      ],
    };
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const rendered = render(<ReportView report={duplicateReport} />);
    const errorCalls = [...errorSpy.mock.calls];
    rendered.unmount();
    errorSpy.mockRestore();

    const duplicateKeyWarnings = errorCalls.filter((call) =>
      call.some((message) => {
        const text = String(message);
        return text.includes('unique "key"') || text.includes('same key');
      }),
    );
    expect(duplicateKeyWarnings).toHaveLength(0);
  });
});
