export type Repository = {
  id: string;
  name: string;
  source_type: 'zip' | 'git' | 'local';
  source_uri?: string | null;
  status: string;
  source_state: string;
  parse_state: string;
  index_state: string;
  parse_warning_count: number;
  parse_warnings: { path: string; code: string }[];
  job?: { id: string; state: string; progress: string; attempt: number; error_code?: string | null } | null;
  error?: string | null;
  default_branch?: string | null;
  indexed_at?: string | null;
  symbol_count: number;
  file_count: number;
};

export type TreeEntry = {
  path: string;
  name: string;
  type: 'file' | 'directory';
};

export type CodeFile = {
  path: string;
  language: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  content: string;
};

export type CodeSymbol = {
  id: string;
  name: string;
  qualified_name: string;
  kind: string;
  language: string;
  file_path: string;
  start_line: number;
  end_line: number;
  signature?: string;
  docstring?: string;
};

export type CodeReference = {
  id: string;
  target_name: string;
  kind: string;
  file_path: string;
  line: number;
  text?: string;
};

export function fileLineHref(repositoryId: string, path: string, line = 1): string {
  const query = new URLSearchParams({ repository: repositoryId, path, line: String(line) });
  return `/code?${query.toString()}`;
}

export function monacoLanguage(path: string): string {
  const extension = path.split('.').pop()?.toLowerCase();
  return ({ py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript', rs: 'rust', cs: 'csharp' } as Record<string, string>)[extension || ''] || extension || 'plaintext';
}
