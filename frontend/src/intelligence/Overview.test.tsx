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
  projects: 3,
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
  });

  it('shows a partial synchronization warning', () => {
    const html = renderOverview(cappedOverview);

    expect(html).toContain('部分项目尚未完成同步');
  });
});
