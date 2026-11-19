export type EditorWorkspace = {
  id: string;
  repository_id: string;
  snapshot_hash: string;
  revision: number;
  file_count: number;
  excluded_paths: string[];
  can_edit: boolean;
};

export type EditorFile = {
  path: string;
  version: string | null;
  content: string | null;
  encoding: string;
  newline: string;
  read_only_reason: string | null;
  size: number;
  revision: number;
};

export type EditorTab = EditorFile & {
  original: string;
  content: string;
  isNew?: boolean;
  latest?: EditorFile;
};

export type Draft = { version: string | null; content: string; isNew?: boolean };

export function dirty(tab: EditorTab): boolean {
  return !!tab.isNew || tab.content !== tab.original;
}

export function openTab(file: EditorFile, draft?: Draft | null): EditorTab {
  const original = file.content ?? '';
  const restore = draft && !file.read_only_reason;
  return {
    ...file, original, content: restore ? draft.content : original,
    isNew: restore ? draft.isNew : undefined,
    latest: restore && draft.version !== file.version ? file : undefined,
    version: restore ? draft.version : file.version,
  };
}

// A user may keep typing while a save is in flight. Only advance the saved base.
export function savedTab(tab: EditorTab, submitted: string, saved: EditorFile): EditorTab {
  return { ...tab, version: saved.version, original: submitted, isNew: false,
    encoding: saved.encoding, newline: saved.newline, revision: saved.revision,
    latest: undefined };
}

export function draftKey(workspaceId: string, path: string): string {
  return `knowra:editor:${workspaceId}:${encodeURIComponent(path)}`;
}

export function parseDraft(value: string | null): Draft | null {
  if (!value || value.length > 2 * 1024 * 1024) return null;
  try {
    const parsed = JSON.parse(value);
    if (typeof parsed.content !== 'string' ||
        !(parsed.version === null || (typeof parsed.version === 'string' && /^[a-f0-9]{64}$/.test(parsed.version)))) return null;
    return { content: parsed.content, version: parsed.version, isNew: parsed.isNew === true };
  } catch { return null; }
}
