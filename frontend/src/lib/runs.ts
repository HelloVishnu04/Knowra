export type RunSummary = {
  id: string;
  route: string;
  planned_routes: string[];
  status: string;
  provider: string;
  model: string;
  created_at: string | null;
  completed_at: string | null;
  query_preview: string;
};

export type TraceStep = {
  node: string;
  status: string;
  at: string;
  details: Record<string, unknown>;
};

export type RetrievalTrace = {
  id: string;
  source: string;
  query: string;
  status: string;
  latency_ms: number;
  result_count: number;
  error?: string | null;
  chunks: Array<{
    id: string;
    source: string;
    score: number;
    preview: string;
    metadata: Record<string, unknown>;
  }>;
};

export type RunDetail = RunSummary & {
  user_query: string;
  answer?: string | null;
  error?: string | null;
  trace: TraceStep[];
  retrievals: RetrievalTrace[];
  citations: Array<Record<string, unknown> & {
    number: number;
    source: string;
    label: string;
  }>;
  tool_calls: Array<{
    id: string;
    name: string;
    arguments: Record<string, unknown>;
    requires_approval: boolean;
    status: string;
    result?: Record<string, unknown> | null;
    error?: string | null;
  }>;
  coding_attempts: Array<{
    id: string;
    repository_id: string;
    attempt: number;
    plan: string;
    patch: string;
    checks: Array<{
      stage: string;
      command: string;
      status: string;
      output?: string;
      exit_code?: number | null;
    }>;
    status: string;
    error?: string | null;
    created_at: string | null;
  }>;
  execution_jobs: Array<{
    id: string;
    repository_id?: string | null;
    attempt: number;
    stage: string;
    command: string[];
    image: string;
    status: string;
    stdout: string;
    stderr: string;
    exit_code?: number | null;
    duration_ms?: number | null;
    error?: string | null;
    created_at: string | null;
    started_at: string | null;
    completed_at: string | null;
  }>;
};

export function humanizeStage(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

export function formatScore(value: number): string {
  return Number.isFinite(value) ? value.toFixed(4) : '—';
}

export function traceStages(run: Pick<RunDetail, 'trace'>): string[] {
  return run.trace.map(step => `${humanizeStage(step.node)} · ${step.status}`);
}
