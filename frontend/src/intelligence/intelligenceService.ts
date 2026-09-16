import apiClient from '../api/client';
import endpoints from '../api/endpoints';
import type {
  IntelligenceOverview,
  IntelligenceProject,
  QueryRequest,
  QueryResult,
} from './types';

interface ProjectsResponse {
  projects: IntelligenceProject[];
}

interface OverviewResponse {
  overview: IntelligenceOverview;
}

type QueryRequestWithToken = QueryRequest & { token: string | null };

function responseMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null && 'message' in payload) {
    const message = (payload as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
}

async function readJson<T>(response: Response | unknown): Promise<T> {
  if (
    !response ||
    typeof response !== 'object' ||
    !('json' in response) ||
    typeof (response as Response).json !== 'function'
  ) {
    throw new Error('情报服务返回了无效响应。');
  }

  const rawResponse = response as Response;
  let payload: unknown;
  try {
    payload = await rawResponse.json();
  } catch {
    throw new Error(
      rawResponse.ok
        ? '情报服务返回了无效 JSON。'
        : `情报服务请求失败（${rawResponse.status}）。`,
    );
  }

  if (!rawResponse.ok) {
    throw new Error(
      responseMessage(payload, `情报服务请求失败（${rawResponse.status}）。`),
    );
  }
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'success' in payload &&
    (payload as { success?: unknown }).success === false
  ) {
    throw new Error(responseMessage(payload, '情报服务请求失败。'));
  }
  return payload as T;
}

const intelligenceService = {
  async getProjects(token: string | null): Promise<IntelligenceProject[]> {
    const response = await readJson<ProjectsResponse>(
      await apiClient.get(endpoints.INTELLIGENCE.PROJECTS, token),
    );
    return response.projects ?? [];
  },

  async getOverview(token: string | null): Promise<IntelligenceOverview> {
    const response = await readJson<OverviewResponse>(
      await apiClient.get(endpoints.INTELLIGENCE.OVERVIEW, token),
    );
    if (!response.overview) throw new Error('概览响应缺少 overview 字段。');
    return response.overview;
  },

  async query({
    token,
    ...request
  }: QueryRequestWithToken): Promise<QueryResult> {
    return readJson<QueryResult>(
      await apiClient.post(endpoints.INTELLIGENCE.QUERY, request, token),
    );
  },
};

export default intelligenceService;
