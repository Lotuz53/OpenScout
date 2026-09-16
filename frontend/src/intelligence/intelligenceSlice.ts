import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import { selectToken } from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import intelligenceService from './intelligenceService';
import type {
  IntelligenceOverview,
  IntelligenceProject,
  QueryFilterPayload,
  QueryFilters,
  QueryIntent,
  QueryResult,
  RequestStatus,
} from './types';

export const createEmptyFilters = (): QueryFilters => ({
  repositories: [],
  source_types: [],
  date_from: null,
  date_to: null,
});

export interface IntelligenceState {
  overview: IntelligenceOverview | null;
  projects: IntelligenceProject[];
  filters: QueryFilters;
  question: string;
  queryResult: QueryResult | null;
  requestStatus: RequestStatus;
  overviewStatus: RequestStatus;
  projectsStatus: RequestStatus;
  error: string | null;
}

export const initialState: IntelligenceState = {
  overview: null,
  projects: [],
  filters: createEmptyFilters(),
  question: '',
  queryResult: null,
  requestStatus: 'idle',
  overviewStatus: 'idle',
  projectsStatus: 'idle',
  error: null,
};

type IntelligenceThunkConfig = {
  state: RootState;
  rejectValue: string;
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function explicitFilterPayload(filters: QueryFilters): QueryFilterPayload {
  const payload: QueryFilterPayload = {};
  if (filters.repositories.length) payload.repositories = filters.repositories;
  if (filters.source_types.length) payload.source_types = filters.source_types;
  if (filters.date_from) payload.date_from = filters.date_from;
  if (filters.date_to) payload.date_to = filters.date_to;
  return payload;
}

export const loadOverview = createAsyncThunk<
  IntelligenceOverview,
  void,
  IntelligenceThunkConfig
>('intelligence/loadOverview', async (_, { getState, rejectWithValue }) => {
  try {
    return await intelligenceService.getOverview(selectToken(getState()));
  } catch (error) {
    return rejectWithValue(errorMessage(error, '无法加载情报概览。'));
  }
});

export const loadProjects = createAsyncThunk<
  IntelligenceProject[],
  void,
  IntelligenceThunkConfig
>('intelligence/loadProjects', async (_, { getState, rejectWithValue }) => {
  try {
    return await intelligenceService.getProjects(selectToken(getState()));
  } catch (error) {
    return rejectWithValue(errorMessage(error, '无法加载情报项目。'));
  }
});

export const queryIntelligence = createAsyncThunk<
  QueryResult,
  { question: string; filters: QueryFilters; intent?: QueryIntent },
  IntelligenceThunkConfig
>(
  'intelligence/query',
  async ({ question, filters, intent }, { getState, rejectWithValue }) => {
    try {
      const normalizedQuestion = question.trim();
      if (!normalizedQuestion) return rejectWithValue('请输入研究问题。');
      return await intelligenceService.query({
        question: normalizedQuestion,
        filters: explicitFilterPayload(filters),
        intent,
        token: selectToken(getState()),
      });
    } catch (error) {
      return rejectWithValue(errorMessage(error, '无法完成情报分析。'));
    }
  },
);

const intelligenceSlice = createSlice({
  name: 'intelligence',
  initialState,
  reducers: {
    setFilters(state, action: PayloadAction<Partial<QueryFilters>>) {
      state.filters = { ...state.filters, ...action.payload };
    },
    setQuestion(state, action: PayloadAction<string>) {
      state.question = action.payload;
    },
    clearQueryResult(state) {
      state.queryResult = null;
      state.requestStatus = 'idle';
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadOverview.pending, (state) => {
        state.overviewStatus = 'loading';
        state.error = null;
      })
      .addCase(loadOverview.fulfilled, (state, action) => {
        state.overviewStatus = 'succeeded';
        state.overview = action.payload;
        state.error = null;
      })
      .addCase(loadOverview.rejected, (state, action) => {
        state.overviewStatus = 'failed';
        state.error =
          action.payload ?? action.error.message ?? '无法加载情报概览。';
      })
      .addCase(loadProjects.pending, (state) => {
        state.projectsStatus = 'loading';
        state.error = null;
      })
      .addCase(loadProjects.fulfilled, (state, action) => {
        state.projectsStatus = 'succeeded';
        state.projects = action.payload;
        state.error = null;
      })
      .addCase(loadProjects.rejected, (state, action) => {
        state.projectsStatus = 'failed';
        state.error =
          action.payload ?? action.error.message ?? '无法加载情报项目。';
      })
      .addCase(queryIntelligence.pending, (state) => {
        state.requestStatus = 'loading';
        state.queryResult = null;
        state.error = null;
      })
      .addCase(queryIntelligence.fulfilled, (state, action) => {
        state.requestStatus = 'succeeded';
        state.queryResult = action.payload;
        state.error = null;
      })
      .addCase(queryIntelligence.rejected, (state, action) => {
        state.requestStatus = 'failed';
        state.error =
          action.payload ?? action.error.message ?? '无法完成情报分析。';
      });
  },
});

export const { clearQueryResult, setFilters, setQuestion } =
  intelligenceSlice.actions;

export const selectIntelligence = (state: RootState) => state.intelligence;
export const selectIntelligenceOverview = (state: RootState) =>
  state.intelligence.overview;
export const selectIntelligenceProjects = (state: RootState) =>
  state.intelligence.projects;
export const selectIntelligenceFilters = (state: RootState) =>
  state.intelligence.filters;
export const selectIntelligenceQuestion = (state: RootState) =>
  state.intelligence.question;
export const selectIntelligenceQueryResult = (state: RootState) =>
  state.intelligence.queryResult;

export default intelligenceSlice.reducer;
