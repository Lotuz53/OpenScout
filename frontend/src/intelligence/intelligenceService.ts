import apiClient from '../api/client';
import endpoints from '../api/endpoints';
import type {
  ComparisonResult,
  IntelligenceOverview,
  IntelligenceProject,
  QueryFilterPayload,
  QueryRequest,
  QueryResult,
  ReportDocument,
  ReportInput,
  ReportShare,
  RepositoryPreflight,
  SharedReport,
} from './types';

interface ProjectsResponse {
  projects: IntelligenceProject[];
}

interface PreflightResponse {
  preflight: RepositoryPreflight;
}

interface ProjectResponse {
  project: IntelligenceProject;
}

interface SyncResponse {
  task_id: string;
}

interface OverviewResponse {
  overview: IntelligenceOverview;
}

interface ComparisonResponse {
  comparison: ComparisonResult;
}

interface ReportResponse {
  report: unknown;
}

interface ReportShareResponse {
  share: ReportShare;
}

interface SharedReportResponse {
  report: unknown;
}

type QueryRequestWithToken = QueryRequest & { token: string | null };
type ComparisonRequestWithToken = {
  project_ids: string[];
  dimensions: string[];
  filters: QueryFilterPayload;
  token: string | null;
};
type ReportRequestWithToken = {
  project_ids: string[];
  results: ReportInput[];
  token: string | null;
};
type ProjectRequestWithToken = {
  repository: string;
  window_start: string;
  window_end: string;
  token: string | null;
};

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

async function readBlob(response: Response | unknown): Promise<Blob> {
  if (
    !response ||
    typeof response !== 'object' ||
    !('blob' in response) ||
    typeof (response as Response).blob !== 'function'
  ) {
    throw new Error('情报服务返回了无效下载响应。');
  }

  const rawResponse = response as Response;
  if (!rawResponse.ok) {
    let message = `情报服务请求失败（${rawResponse.status}）。`;
    try {
      const payload = await rawResponse.json();
      message = responseMessage(payload, message);
    } catch {
      // Keep the HTTP status when an error response is not JSON.
    }
    throw new Error(message);
  }
  return rawResponse.blob();
}

function normalizeReport(value: unknown): ReportDocument {
  if (typeof value !== 'object' || value === null) {
    throw new Error('报告响应缺少 report 字段。');
  }

  const row = value as Record<string, unknown>;
  const reportData =
    typeof row.report_data === 'object' && row.report_data !== null
      ? (row.report_data as Record<string, unknown>)
      : row;
  const title = reportData.title;
  const sections = reportData.sections;
  const sources = reportData.sources;
  if (
    typeof title !== 'string' ||
    !Array.isArray(sections) ||
    !Array.isArray(sources)
  ) {
    throw new Error('报告响应缺少结构化内容。');
  }

  const report = {
    ...reportData,
    title,
    sections,
    sources,
    id:
      typeof row.id === 'string'
        ? row.id
        : typeof reportData.id === 'string'
          ? reportData.id
          : null,
    created_at:
      typeof reportData.created_at === 'string'
        ? reportData.created_at
        : typeof row.created_at === 'string'
          ? row.created_at
          : new Date().toISOString(),
  };
  return report as unknown as ReportDocument;
}

function normalizeSharedReport(value: unknown): SharedReport {
  if (typeof value !== 'object' || value === null) {
    throw new Error('共享报告响应缺少 report 字段。');
  }

  const row = value as Record<string, unknown>;
  const title = row.title;
  const sections = row.sections;
  const sources = row.sources;
  const coverage = row.coverage;
  if (
    typeof title !== 'string' ||
    !Array.isArray(sections) ||
    !Array.isArray(sources) ||
    typeof coverage !== 'object' ||
    coverage === null
  ) {
    throw new Error('共享报告响应缺少结构化内容。');
  }

  const normalizedSections = sections.map((section) => {
    if (typeof section !== 'object' || section === null) {
      throw new Error('共享报告章节格式无效。');
    }
    const item = section as Record<string, unknown>;
    if (
      typeof item.heading !== 'string' ||
      !Array.isArray(item.paragraphs) ||
      !Array.isArray(item.bullets) ||
      item.paragraphs.some((paragraph) => typeof paragraph !== 'string') ||
      item.bullets.some((bullet) => typeof bullet !== 'string')
    ) {
      throw new Error('共享报告章节格式无效。');
    }
    return {
      heading: item.heading,
      paragraphs: item.paragraphs as string[],
      bullets: item.bullets as string[],
    };
  });

  const normalizedSources = sources.map((source) => {
    if (typeof source !== 'object' || source === null) {
      throw new Error('共享报告来源格式无效。');
    }
    const item = source as Record<string, unknown>;
    if (typeof item.title !== 'string' || typeof item.url !== 'string') {
      throw new Error('共享报告来源格式无效。');
    }
    return { title: item.title, url: item.url };
  });

  const rawCoverage = coverage as Record<string, unknown>;
  const rawCounts = rawCoverage.counts;
  const counts: Record<string, number> = {};
  if (typeof rawCounts === 'object' && rawCounts !== null) {
    for (const [key, count] of Object.entries(rawCounts)) {
      if (typeof count === 'number' && Number.isFinite(count)) {
        counts[key] = count;
      }
    }
  }

  return {
    title,
    sections: normalizedSections,
    sources: normalizedSources,
    coverage: {
      repositories: Array.isArray(rawCoverage.repositories)
        ? rawCoverage.repositories.filter(
            (repository): repository is string =>
              typeof repository === 'string',
          )
        : [],
      date_from:
        typeof rawCoverage.date_from === 'string'
          ? rawCoverage.date_from
          : null,
      date_to:
        typeof rawCoverage.date_to === 'string' ? rawCoverage.date_to : null,
      counts,
      capped: rawCoverage.capped === true,
    },
    created_at: typeof row.created_at === 'string' ? row.created_at : null,
  };
}

const intelligenceService = {
  async preflight(
    repository: string,
    token: string | null,
  ): Promise<RepositoryPreflight> {
    const response = await readJson<PreflightResponse>(
      await apiClient.post(
        endpoints.INTELLIGENCE.PREFLIGHT,
        { repository },
        token,
      ),
    );
    if (!response.preflight) {
      throw new Error('预检响应缺少 preflight 字段。');
    }
    return response.preflight;
  },

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

  async createProject({ token, ...request }: ProjectRequestWithToken) {
    const response = await readJson<ProjectResponse>(
      await apiClient.post(endpoints.INTELLIGENCE.PROJECTS, request, token),
    );
    if (!response.project) throw new Error('创建响应缺少 project 字段。');
    return response.project;
  },

  async syncProject(projectId: string, token: string | null): Promise<string> {
    const response = await readJson<SyncResponse>(
      await apiClient.post(
        endpoints.INTELLIGENCE.PROJECT_SYNC(projectId),
        {},
        token,
      ),
    );
    if (!response.task_id) throw new Error('同步响应缺少 task_id 字段。');
    return response.task_id;
  },

  async query({
    token,
    ...request
  }: QueryRequestWithToken): Promise<QueryResult> {
    return readJson<QueryResult>(
      await apiClient.post(endpoints.INTELLIGENCE.QUERY, request, token),
    );
  },

  async compare({
    token,
    ...request
  }: ComparisonRequestWithToken): Promise<ComparisonResult> {
    const response = await readJson<ComparisonResponse>(
      await apiClient.post(endpoints.INTELLIGENCE.COMPARISON, request, token),
    );
    if (!response.comparison) throw new Error('对比响应缺少 comparison 字段。');
    return response.comparison;
  },

  async createReport({
    token,
    ...request
  }: ReportRequestWithToken): Promise<ReportDocument> {
    const response = await readJson<ReportResponse>(
      await apiClient.post(endpoints.INTELLIGENCE.REPORTS, request, token),
    );
    return normalizeReport(response.report);
  },

  async getReport(
    reportId: string,
    token: string | null,
  ): Promise<ReportDocument> {
    const response = await readJson<ReportResponse>(
      await apiClient.get(endpoints.INTELLIGENCE.REPORT(reportId), token),
    );
    return normalizeReport(response.report);
  },

  async createReportShare(
    reportId: string,
    token: string | null,
  ): Promise<ReportShare> {
    const response = await readJson<ReportShareResponse>(
      await apiClient.post(
        endpoints.INTELLIGENCE.REPORT_SHARE(reportId),
        {},
        token,
      ),
    );
    if (
      !response.share ||
      typeof response.share.token !== 'string' ||
      typeof response.share.path !== 'string'
    ) {
      throw new Error('分享响应缺少链接字段。');
    }
    return response.share;
  },

  async revokeReportShare(
    reportId: string,
    token: string | null,
  ): Promise<void> {
    const response = await apiClient.delete(
      endpoints.INTELLIGENCE.REPORT_SHARE(reportId),
      token,
    );
    if (!response || typeof response !== 'object' || response.ok !== true) {
      throw new Error('撤销分享链接失败。');
    }
  },

  async getSharedReport(token: string): Promise<SharedReport> {
    const response = await readJson<SharedReportResponse>(
      await apiClient.get(endpoints.INTELLIGENCE.PUBLIC_REPORT(token), null),
    );
    return normalizeSharedReport(response.report);
  },

  async downloadReport({
    reportId,
    format,
    token,
  }: {
    reportId: string;
    format: 'markdown' | 'pdf';
    token: string | null;
  }): Promise<Blob> {
    return readBlob(
      await apiClient.get(
        endpoints.INTELLIGENCE.REPORT_DOWNLOAD(reportId, format),
        token,
      ),
    );
  },
};

export default intelligenceService;
