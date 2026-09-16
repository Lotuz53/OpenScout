import '@testing-library/jest-dom/vitest';

import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import intelligenceService from './intelligenceService';
import SharedReportView from './SharedReportView';
import type { SharedReport } from './types';

vi.mock('./intelligenceService', () => ({
  default: {
    getSharedReport: vi.fn(),
  },
}));

const report: SharedReport = {
  title: 'OpenScout AI 产品情报报告',
  sections: [
    {
      heading: '执行摘要',
      paragraphs: ['公开摘要'],
      bullets: ['公开要点'],
    },
  ],
  sources: [
    {
      title: '公开来源',
      url: 'https://github.com/example/project/issues/1',
    },
  ],
  coverage: {
    repositories: ['example/project'],
    date_from: '2026-01-01',
    date_to: '2026-09-01',
    counts: { issue: 1 },
    capped: false,
  },
  created_at: '2026-09-01T00:00:00Z',
};

const getSharedReport = vi.mocked(intelligenceService.getSharedReport);

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={['/reports/shared/share-token']}>
      <Routes>
        <Route path="/reports/shared/:token" element={<SharedReportView />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('SharedReportView', () => {
  beforeEach(() => {
    getSharedReport.mockReset();
  });

  it('renders the read-only report and source links without private controls', async () => {
    getSharedReport.mockResolvedValue(report);

    renderRoute();

    expect(
      await screen.findByRole('heading', { name: report.title }),
    ).toBeInTheDocument();
    expect(screen.getByText('公开摘要')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /公开来源/ })).toHaveAttribute(
      'href',
      report.sources[0].url,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText(/下载|重新同步|编辑/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/user_id|trace|owner-secret/),
    ).not.toBeInTheDocument();
    expect(getSharedReport).toHaveBeenCalledWith('share-token');
  });

  it('shows a safe unavailable state for a revoked link', async () => {
    getSharedReport.mockRejectedValue(new Error('report not found'));

    renderRoute();

    expect(
      await screen.findByRole('heading', { name: '共享报告不可用' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/链接可能已失效/)).toBeInTheDocument();
  });
});
