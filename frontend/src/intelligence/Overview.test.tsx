import { configureStore } from '@reduxjs/toolkit';
import { renderToStaticMarkup } from 'react-dom/server';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import preferenceReducer from '../preferences/preferenceSlice';
import IntelligenceOverview from './Overview';
import reducer, { initialState } from './intelligenceSlice';
import type { IntelligenceOverview as OverviewData } from './types';

const cappedOverview: OverviewData = {
  projects: 7,
  records: 3012,
  counts: {
    documentation: 30,
    issue: 1000,
    issue_comment: 1970,
    release: 12,
  },
  coverage: {
    date_from: '2025-09-14',
    date_to: '2026-09-14',
  },
  last_synced_at: '2026-09-14T08:00:00Z',
  statuses: { ready: 2, partial: 1 },
  capped: true,
  latest_version: 'v1.2.3',
  topics: [
    {
      cluster_id: 'topic-1',
      label: 'SSO',
      repository: 'o/r',
      month: '2026-01',
      count: 4,
      snapshot_id: 'snapshot-1',
    },
  ],
};

const partialRunOverview: OverviewData = {
  ...cappedOverview,
  latest_sync_run: {
    id: 'run-1',
    project_id: 'project-1',
    status: 'partial',
    counts: { documentation: 3, issue: 7, release: 1 },
    failures: [
      {
        source_type: 'issue',
        category: 'network',
        retryable: true,
        message: 'temporary failure',
      },
    ],
    coverage: {
      repositories: ['o/r'],
      date_from: '2026-01-01',
      date_to: '2026-09-16',
      capped: false,
      last_synced_at: null,
    },
    started_at: '2026-09-16T08:30:00Z',
    finished_at: '2026-09-16T08:31:00Z',
  },
};

function renderOverview(overview: OverviewData): string {
  const store = configureStore({
    reducer: {
      intelligence: reducer,
      preference: preferenceReducer,
    },
    preloadedState: {
      intelligence: {
        ...initialState,
        overview,
        overviewStatus: 'succeeded' as const,
        projectsStatus: 'succeeded' as const,
      },
    },
  });

  return renderToStaticMarkup(
    <Provider store={store}>
      <MemoryRouter>
        <IntelligenceOverview />
      </MemoryRouter>
    </Provider>,
  );
}

describe('intelligence overview', () => {
  it('shows capped coverage as a warning', () => {
    const html = renderOverview(cappedOverview);

    expect(html).toContain('已达到 1,000 条 Issue 上限');
    expect(html).toContain('文档');
    expect(html).toContain('Issue');
    expect(html).toContain('Release');
    expect(html).toContain('v1.2.3');
    expect(html).toContain('SSO');
    expect(html).toContain('0 / 7');
  });

  it('shows a partial synchronization warning', () => {
    const html = renderOverview(cappedOverview);

    expect(html).toContain('部分项目尚未完成同步');
  });

  it('renders real sync failures from the latest run', () => {
    const html = renderOverview(partialRunOverview);

    expect(html).toContain('1 个来源需要关注');
    expect(html).toContain('Issue · 网络暂时不可用');
    expect(html).toContain('可以重试');
  });
});
