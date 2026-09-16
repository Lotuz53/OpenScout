import { describe, expect, it } from 'vitest';

import type { QueryResult } from './types';
import reducer, {
  initialState,
  queryIntelligence,
  setFilters,
  setQuestion,
} from './intelligenceSlice';

const queryResult: QueryResult = {
  answer: 'Dify added SSO.',
  claims: [],
  evidence: [],
  coverage: {
    repositories: ['langgenius/dify'],
    date_from: '2025-09-14',
    date_to: '2026-09-14',
    counts: { release: 1 },
    capped: false,
    last_synced_at: null,
  },
  latency_ms: 42,
  trace: {
    intent: 'factual',
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

describe('intelligence reducer', () => {
  it('starts with an explicit empty filter contract', () => {
    const state = reducer(undefined, { type: '@@INIT' });

    expect(state).toMatchObject({
      overview: null,
      filters: {
        repositories: [],
        source_types: [],
        date_from: null,
        date_to: null,
      },
      question: '',
      queryResult: null,
      requestStatus: 'idle',
      error: null,
    });
  });

  it('updates filters and question without changing the query result', () => {
    const withResult = reducer(
      { ...initialState, queryResult },
      setFilters({ repositories: ['langgenius/dify'] }),
    );
    const state = reducer(withResult, setQuestion('最近有哪些变化？'));

    expect(state.filters.repositories).toEqual(['langgenius/dify']);
    expect(state.question).toBe('最近有哪些变化？');
    expect(state.queryResult).toBe(queryResult);
  });

  it('stores a successful query result and clears a previous error', () => {
    const action = queryIntelligence.fulfilled(queryResult, 'request-1', {
      question: '最近有哪些变化？',
      filters: initialState.filters,
    });
    const state = reducer(
      { ...initialState, error: 'previous error', requestStatus: 'loading' },
      action,
    );

    expect(state.requestStatus).toBe('succeeded');
    expect(state.queryResult).toBe(queryResult);
    expect(state.error).toBeNull();
  });
});
