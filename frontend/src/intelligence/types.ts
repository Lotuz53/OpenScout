/** Shared TypeScript contracts for the OpenScout intelligence API. */

export const SOURCE_TYPES = [
  'documentation',
  'issue',
  'issue_comment',
  'release',
] as const;

export type SourceType = (typeof SOURCE_TYPES)[number];

export const QUERY_INTENTS = [
  'factual',
  'temporal',
  'comparative',
  'aggregate',
  'relational',
] as const;

export type QueryIntent = (typeof QUERY_INTENTS)[number];

export type RetrievalStrategy =
  'hybrid' | 'hybrid_rerank' | 'sql_plus_hybrid' | 'split_hybrid' | 'graphrag';

export type ClaimKind = 'fact' | 'statistic' | 'inference';
export type Confidence = 'low' | 'medium' | 'high';

export type ProjectStatus =
  'draft' | 'syncing' | 'ready' | 'partial' | 'failed';

export type RequestStatus = 'idle' | 'loading' | 'succeeded' | 'failed';

export type RepositoryPreflightErrorCode =
  | 'invalid_repository'
  | 'not_found'
  | 'private_not_supported'
  | 'github_unavailable';

export interface RepositoryPreflight {
  repository: string;
  default_branch: string | null;
  archived: boolean;
  estimated_counts: Partial<
    Record<'issues' | 'releases' | 'documents', number>
  >;
  warnings: string[];
  error_code: RepositoryPreflightErrorCode | null;
  message: string | null;
}

export interface IntelligenceProject {
  id: string;
  user_id: string;
  repository: string;
  window_start: string;
  window_end: string;
  status: ProjectStatus;
  last_synced_at: string | null;
  /** Optional fields supplied by an enriched overview response. */
  latest_version?: string | null;
}

export interface QueryFilters {
  repositories: string[];
  source_types: SourceType[];
  date_from: string | null;
  date_to: string | null;
}

export type QueryFilterPayload = Partial<QueryFilters>;

export interface QueryRequest {
  question: string;
  filters: QueryFilterPayload;
}

export interface Evidence {
  id: string;
  record_id: string;
  repository: string;
  source_type: SourceType;
  title: string;
  excerpt: string;
  source_url: string;
  occurred_at: string | null;
  author: string | null;
}

export interface Claim {
  id: string;
  text: string;
  kind: ClaimKind;
  evidence_ids: string[];
  confidence: Confidence;
}

export interface Coverage {
  repositories: string[];
  date_from: string | null;
  date_to: string | null;
  counts: Partial<Record<SourceType, number>>;
  capped: boolean;
  last_synced_at: string | null;
}

export interface FilterSource {
  field: 'repositories' | 'source_types' | 'date_from' | 'date_to';
  value: unknown;
  source: 'explicit' | 'inferred';
}

export interface RetrievalTrace {
  intent: QueryIntent;
  strategy: RetrievalStrategy;
  fallback_reason: string | null;
  applied_filters: QueryFilters;
  explicit_filters: QueryFilters;
  inferred_filters: QueryFilters;
  filter_sources: FilterSource[];
}

export interface QueryResult {
  answer: string;
  claims: Claim[];
  evidence: Evidence[];
  coverage: Coverage;
  latency_ms: number;
  trace: RetrievalTrace;
}

export type ComparisonStatus = 'supported' | 'not_supported' | 'unknown';

export interface ComparisonCell {
  status: ComparisonStatus;
  display_label: string;
  first_evidence_date: string | null;
  community_signal_count: number;
  evidence_ids: string[];
  coverage_warning: string | null;
}

export interface ComparisonRow {
  dimension: string;
  cells: Record<string, ComparisonCell>;
}

export interface ComparisonResult {
  repositories: string[];
  rows: ComparisonRow[];
  coverage_warnings: Record<string, string | null>;
}

export interface ReportSection {
  heading: string;
  paragraphs: string[];
  bullets: string[];
}

export interface ReportSource {
  id: string;
  title: string;
  url: string;
  repository: string;
  source_type: string;
  excerpt: string;
}

export interface ReportDocument {
  title: string;
  user_id: string;
  project_ids: string[];
  sections: ReportSection[];
  sources: ReportSource[];
  id: string | null;
  source_ids: string[];
  created_at: string;
}

export type ReportInput = QueryResult | ComparisonResult;

export interface OverviewCoverage {
  date_from: string | null;
  date_to: string | null;
  capped?: boolean;
}

export interface TopicTrend {
  cluster_id: string;
  label: string;
  repository: string;
  month: string;
  count: number;
  snapshot_id: string;
}

export interface IntelligenceOverview {
  projects: number;
  records: number;
  counts: Partial<Record<SourceType, number>>;
  coverage: OverviewCoverage;
  last_synced_at: string | null;
  statuses: Partial<Record<ProjectStatus, number>>;
  /** Optional fields reserved for an enriched overview response. */
  capped?: boolean;
  latest_version?: string | null;
  topics?: TopicTrend[];
}
