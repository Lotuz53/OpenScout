import '@testing-library/jest-dom/vitest';

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import SyncStatus, { type SyncRun } from './SyncStatus';

const partialRun: SyncRun = {
  id: 'run-1',
  status: 'partial',
  counts: {
    documentation: 8,
    issue: 42,
    issue_comment: 120,
    release: 2,
  },
  failures: [
    {
      source_type: 'issue',
      category: 'rate_limit',
      retryable: true,
      message: 'GitHub rate limit reached',
    },
  ],
  coverage: {
    repositories: ['owner/repo'],
    date_from: '2026-01-01',
    date_to: '2026-09-16',
    capped: false,
    last_synced_at: '2026-09-16T08:30:00Z',
  },
  started_at: '2026-09-16T08:30:00Z',
  finished_at: '2026-09-16T08:31:00Z',
};

describe('SyncStatus', () => {
  it('shows partial counts and a retry action', () => {
    const onRetry = vi.fn();

    render(<SyncStatus run={partialRun} onRetry={onRetry} />);

    expect(screen.getByText('部分完成')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试失败项' })).toBeEnabled();
    expect(screen.getByText('Issue')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('labels local synchronization failures clearly', () => {
    const failedRun: SyncRun = {
      ...partialRun,
      status: 'failed',
      failures: [
        {
          source_type: 'sync',
          category: 'local',
          retryable: false,
          message: 'FAISS save failed',
        },
      ],
    };

    render(<SyncStatus run={failedRun} />);

    expect(screen.getByText('同步流程 · 本地同步失败')).toBeInTheDocument();
  });
});
