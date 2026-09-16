import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const intelligenceMocks = vi.hoisted(() => ({
  getProjects: vi.fn(),
  getOverview: vi.fn(),
  query: vi.fn(),
}));

vi.mock('./intelligenceService', () => ({
  default: intelligenceMocks,
}));

import preferenceReducer from '../preferences/preferenceSlice';
import Workbench from './Workbench';
import reducer, { initialState } from './intelligenceSlice';
import type { IntelligenceProject, QueryResult } from './types';

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const project: IntelligenceProject = {
  id: 'project-1',
  user_id: 'user-1',
  repository: 'langgenius/dify',
  window_start: '2025-09-14',
  window_end: '2026-09-14',
  status: 'ready',
  last_synced_at: null,
};

const queryResult: QueryResult = {
  answer: '当前收录数据无法支持该结论。',
  claims: [],
  evidence: [],
  coverage: {
    repositories: ['langgenius/dify'],
    date_from: null,
    date_to: null,
    counts: {},
    capped: false,
    last_synced_at: null,
  },
  latency_ms: 10,
  trace: {
    intent: 'temporal',
    strategy: 'hybrid',
    fallback_reason: null,
    applied_filters: {
      repositories: ['langgenius/dify'],
      source_types: [],
      date_from: null,
      date_to: null,
    },
    explicit_filters: {
      repositories: ['langgenius/dify'],
      source_types: [],
      date_from: null,
      date_to: null,
    },
    inferred_filters: {
      repositories: [],
      source_types: [],
      date_from: null,
      date_to: null,
    },
    filter_sources: [],
  },
};

function createTestStore() {
  return configureStore({
    reducer: {
      intelligence: reducer,
      preference: preferenceReducer,
    },
    preloadedState: {
      intelligence: {
        ...initialState,
        projects: [project],
        projectsStatus: 'succeeded' as const,
      },
    },
  });
}

async function mountWorkbench(): Promise<{
  container: HTMLDivElement;
  root: Root;
}> {
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <Provider store={createTestStore()}>
        <MemoryRouter>
          <Workbench />
        </MemoryRouter>
      </Provider>,
    );
  });
  return { container, root };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('intelligence workbench', () => {
  it('sends explicit filters with the question', async () => {
    intelligenceMocks.query.mockResolvedValue(queryResult);
    const { container, root } = await mountWorkbench();

    const repository = container.querySelector(
      'input[aria-label="Dify"]',
    ) as HTMLInputElement;
    const question = container.querySelector(
      'textarea[aria-label="研究问题"]',
    ) as HTMLTextAreaElement;
    const submit = container.querySelector(
      'button[type="submit"]',
    ) as HTMLButtonElement;
    const form = container.querySelector('form') as HTMLFormElement;

    await act(async () => {
      repository.click();
      repository.dispatchEvent(new Event('change', { bubbles: true }));
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )?.set;
      setter?.call(question, '最近有哪些变化？');
      question.dispatchEvent(new Event('input', { bubbles: true }));
      question.dispatchEvent(new Event('change', { bubbles: true }));
    });

    await act(async () => {
      submit.click();
      form.dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true }),
      );
      await Promise.resolve();
    });

    expect(intelligenceMocks.query).toHaveBeenCalledWith(
      expect.objectContaining({
        question: '最近有哪些变化？',
        filters: { repositories: ['langgenius/dify'] },
      }),
    );

    root.unmount();
  });
});
