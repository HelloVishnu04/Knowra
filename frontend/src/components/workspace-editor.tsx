'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import { monacoLanguage, type TreeEntry } from '@/lib/code';
import { dirty, draftKey, openTab, parseDraft, savedTab, type EditorFile, type EditorTab, type EditorWorkspace } from '@/lib/editor';

const Editor = dynamic(() => import('@monaco-editor/react'), { ssr: false });
const DiffEditor = dynamic(() => import('@monaco-editor/react').then(module => module.DiffEditor), { ssr: false });
const button = 'rounded border border-slate-600 px-3 py-2 text-xs hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40';
type TreePage = { entries: TreeEntry[]; total: number; next_offset: number | null };

function Folder({ workspaceId, path = '', label = 'Files', hidden, epoch, onOpen }: {
  workspaceId: string; path?: string; label?: string; hidden: boolean; epoch: number; onOpen: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(!path);
  const [page, setPage] = useState<TreePage | null>(null);
  const [error, setError] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    api<TreePage>(`/editor-workspaces/${workspaceId}/tree?directory=${encodeURIComponent(path)}&hidden=${hidden}`, { signal: controller.signal })
      .then(result => { setPage(result); setError(''); })
      .catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message); });
    return () => controller.abort();
  }, [expanded, workspaceId, path, hidden, epoch]);

  const more = async () => {
    if (page?.next_offset == null || loadingMore) return;
    setLoadingMore(true);
    try {
      const result = await api<TreePage>(`/editor-workspaces/${workspaceId}/tree?directory=${encodeURIComponent(path)}&hidden=${hidden}&offset=${page.next_offset}`);
      setPage({ ...result, entries: [...page.entries, ...result.entries] });
    } catch (reason) { setError((reason as Error).message); } finally { setLoadingMore(false); }
  };

  return <div>
    <button aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs text-slate-200 hover:bg-slate-800"><span aria-hidden="true">{expanded ? '▾' : '▸'}</span><span className="truncate">{label}</span></button>
    {expanded && <div className={path ? 'ml-3 border-l border-slate-800 pl-1' : ''}>
      {!page && !error && <p className="p-2 text-xs text-slate-400">Loading files…</p>}
      {page?.entries.map(entry => entry.type === 'directory'
        ? <Folder key={entry.path} workspaceId={workspaceId} path={entry.path} label={entry.name} hidden={hidden} epoch={epoch} onOpen={onOpen} />
        : <button key={entry.path} title={entry.path} onClick={() => onOpen(entry.path)} className="block w-full truncate rounded px-3 py-2 text-left font-mono text-xs text-slate-300 hover:bg-slate-800">{entry.name}</button>)}
      {page && !page.total && <p className="p-2 text-xs text-slate-400">No visible files.</p>}
      {page?.next_offset != null && <button className={`${button} m-2`} disabled={loadingMore} onClick={() => void more()}>Load more ({page.entries.length} of {page.total})</button>}
      {error && <p role="alert" className="p-2 text-xs text-red-300">{error}</p>}
    </div>}
  </div>;
}

export default function WorkspaceEditor({ repositoryId }: { repositoryId: string }) {
  const [workspace, setWorkspace] = useState<EditorWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const tabsRef = useRef<EditorTab[]>([]);
  const [activePath, setActivePath] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [hidden, setHidden] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [newPath, setNewPath] = useState('');
  const [drafts, setDrafts] = useState<string[]>([]);
  const active = tabs.find(tab => tab.path === activePath);
  const hasUnsaved = tabs.some(dirty);

  function loadDraftList(workspaceId: string) {
    try {
      const prefix = `knowra:editor:${workspaceId}:`;
      setDrafts(Object.keys(localStorage).filter(key => key.startsWith(prefix) && parseDraft(localStorage.getItem(key))).map(key => decodeURIComponent(key.slice(prefix.length))));
    } catch { setNotice('Browser draft storage is unavailable. Save before leaving this page.'); }
  }

  function changeTabs(transform: (current: EditorTab[]) => EditorTab[]) {
    const next = transform(tabsRef.current);
    tabsRef.current = next;
    setTabs(next);
    if (!workspace) return;
    try {
      for (const tab of next) {
        if (dirty(tab)) localStorage.setItem(draftKey(workspace.id, tab.path), JSON.stringify({ version: tab.version, content: tab.content, isNew: tab.isNew }));
        else localStorage.removeItem(draftKey(workspace.id, tab.path));
      }
      loadDraftList(workspace.id);
    } catch { setNotice('Browser draft storage is full or unavailable. Save before leaving this page.'); }
  }

  useEffect(() => {
    let mounted = true;
    api<EditorWorkspace[]>(`/editor-workspaces?repository_id=${encodeURIComponent(repositoryId)}`)
      .then(items => { if (mounted) { setWorkspace(items[0] ?? null); if (items[0]) loadDraftList(items[0].id); } })
      .catch(reason => { if (mounted) setError((reason as Error).message); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [repositoryId]);

  useEffect(() => {
    if (!hasUnsaved) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const navigate = (event: MouseEvent) => {
      const anchor = (event.target as Element).closest?.('a[href]') as HTMLAnchorElement | null;
      if (anchor && anchor.href !== window.location.href && !window.confirm('Leave with unsaved edits? Recovery drafts stay in this browser when storage is available.')) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    window.addEventListener('beforeunload', unload);
    document.addEventListener('click', navigate, true);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', navigate, true); };
  }, [hasUnsaved]);

  useEffect(() => {
    const save = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); document.querySelector<HTMLButtonElement>('[data-editor-save]')?.click();
      }
    };
    window.addEventListener('keydown', save);
    return () => window.removeEventListener('keydown', save);
  }, []);

  async function createWorkspace() {
    setBusy(true); setError('');
    try {
      const created = await api<EditorWorkspace>('/editor-workspaces', { method: 'POST', body: JSON.stringify({ repository_id: repositoryId }) });
      setWorkspace(created); loadDraftList(created.id);
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  async function openFile(path: string, create = false) {
    if (!workspace) return;
    const normalized = path.replaceAll('\\', '/');
    if (tabsRef.current.some(tab => tab.path === normalized)) { setActivePath(normalized); return; }
    if (tabsRef.current.length >= 8) { setError('Close a tab before opening another file (8 tabs maximum).'); return; }
    try {
      let draft = null;
      try { draft = parseDraft(localStorage.getItem(draftKey(workspace.id, normalized))); } catch { /* Saving remains available. */ }
      let file: EditorFile;
      try { file = await api<EditorFile>(`/editor-workspaces/${workspace.id}/file?path=${encodeURIComponent(normalized)}`); }
      catch (reason) {
        if (!(reason instanceof ApiError) || reason.status !== 404 || !(create || draft?.isNew)) throw reason;
        file = { path: normalized, version: null, content: '', encoding: 'utf-8', newline: 'lf', read_only_reason: null, size: 0, revision: workspace.revision };
      }
      const tab = openTab(file, draft);
      if (file.version === null) tab.isNew = true;
      changeTabs(current => current.some(item => item.path === normalized) || current.length >= 8 ? current : [...current, tab]);
      if (!tabsRef.current.some(item => item.path === normalized)) { setError('Close a tab before opening another file (8 tabs maximum).'); return; }
      setActivePath(normalized); setError(''); setNewPath('');
      if (draft) setNotice('Recovered a browser draft. Review it before saving.');
    } catch (reason) { setError((reason as Error).message); }
  }

  async function saveFile(reviewed = false) {
    if (!workspace || !active || busy || active.read_only_reason || !workspace.can_edit) return;
    if (active.latest && !reviewed) return;
    const submitted = active.content;
    const path = active.path;
    setBusy(true); setError('');
    try {
      const saved = await api<EditorFile>(`/editor-workspaces/${workspace.id}/file`, { method: 'PUT', body: JSON.stringify({ path, content: submitted, expected_version: reviewed ? active.latest?.version : active.version }) });
      changeTabs(current => current.map(tab => tab.path === path ? savedTab(tab, submitted, saved) : tab));
      setEpoch(current => current + 1); setNotice(`Saved ${path}.`);
    } catch (reason) {
      setError((reason as Error).message);
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const latest = await api<EditorFile>(`/editor-workspaces/${workspace.id}/file?path=${encodeURIComponent(path)}`);
          changeTabs(current => current.map(tab => tab.path === path && tab.version !== latest.version ? { ...tab, latest } : tab));
        } catch { /* Keep the edit and its original expected version. */ }
      }
    } finally { setBusy(false); }
  }

  function closeTab(tab: EditorTab) {
    if (busy || (dirty(tab) && !window.confirm(`Discard unsaved edits to ${tab.path}?`))) return;
    if (workspace) { try { localStorage.removeItem(draftKey(workspace.id, tab.path)); } catch { /* Storage may be disabled. */ } }
    changeTabs(current => current.filter(item => item.path !== tab.path));
    if (activePath === tab.path) setActivePath(tabsRef.current[0]?.path || '');
  }

  return <div className="flex h-full min-h-0 flex-col bg-slate-950 text-slate-100">
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-900 px-4 py-3">
      <div className="mr-auto"><h1 className="font-semibold">Your working copy</h1><p className="text-xs text-slate-400">Explicit saves · private to you · independent of repository indexing</p></div>
      <Link href={`/code?repository=${encodeURIComponent(repositoryId)}`} className={button}>Browse imported repository</Link>
      {workspace && <button data-editor-save disabled={!active || !dirty(active) || !!active.latest || !!active.read_only_reason || busy || !workspace.can_edit} className={`${button} border-cyan-600 text-cyan-200`} onClick={() => void saveFile()}>{busy ? 'Saving…' : 'Save file'}</button>}
    </header>
    {error && <div role="alert" className="flex gap-3 bg-red-950 px-4 py-3 text-sm text-red-200"><span>{error}</span><button className="ml-auto underline" onClick={() => setError('')}>Dismiss</button></div>}
    {notice && <p role="status" className="border-b border-slate-800 px-4 py-2 text-xs text-slate-300">{notice}</p>}
    {loading ? <p role="status" className="p-8 text-sm text-slate-300">Opening your workspace…</p> : !workspace ? <div className="grid flex-1 place-items-center p-6"><div className="max-w-lg space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6"><h2 className="text-xl font-semibold">Start a personal working copy</h2><p className="text-sm leading-6 text-slate-300">Create a copy of the available source files with a saved starting snapshot. Your edits are saved separately from the imported repository and other people’s copies.</p><p className="text-xs leading-5 text-slate-400">Git metadata, dependency folders, build caches, and linked files are excluded. Commits, pushing, and execution are not available in this editor yet.</p><button className={button} disabled={busy || !repositoryId} onClick={() => void createWorkspace()}>{busy ? 'Creating working copy…' : 'Create working copy'}</button></div></div> : <>
      <div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-slate-800 px-4 py-2 text-xs text-slate-300"><span>{workspace.file_count} files in starting snapshot</span><span>Snapshot {workspace.snapshot_hash.slice(0, 10)}</span><span>Working copy search index: unavailable</span>{!workspace.can_edit && <span className="text-amber-200">Read-only workspace role</span>}{workspace.excluded_paths.length > 0 && <details className="w-full"><summary className="cursor-pointer">{workspace.excluded_paths.length} excluded paths</summary><ul className="mt-2 max-h-32 overflow-auto font-mono">{workspace.excluded_paths.map(path => <li key={path}>{path}</li>)}</ul></details>}</div>
      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="max-h-48 overflow-auto border-b border-slate-800 bg-slate-900 p-3 md:max-h-none md:border-r md:border-b-0">
          <label className="mb-3 flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={hidden} onChange={event => setHidden(event.target.checked)} />Show hidden files</label>
          <form onSubmit={event => { event.preventDefault(); if (newPath.trim()) void openFile(newPath.trim(), true); }} className="mb-3 space-y-2"><label className="block text-xs text-slate-300" htmlFor="new-file-path">Open or create file</label><input id="new-file-path" value={newPath} onChange={event => setNewPath(event.target.value)} placeholder="src/example.ts" maxLength={1000} className="w-full rounded border border-slate-600 bg-slate-950 p-2 text-xs" /><button className={button} disabled={!newPath.trim() || !workspace.can_edit}>Open path</button></form>
          {drafts.length > 0 && <details className="mb-3 text-xs text-amber-200"><summary className="cursor-pointer">Browser drafts ({drafts.length})</summary>{drafts.map(path => <button key={path} onClick={() => void openFile(path)} title={path} className="mt-1 block w-full truncate rounded p-2 text-left hover:bg-slate-800">Restore {path}</button>)}</details>}
          <Folder workspaceId={workspace.id} hidden={hidden} epoch={epoch} onOpen={path => void openFile(path)} />
        </aside>
        <main className="flex min-h-72 min-w-0 flex-col md:min-h-0">
          <div role="tablist" aria-label="Open files" className="flex min-h-11 overflow-x-auto border-b border-slate-800">{tabs.map(tab => <div key={tab.path} className={`flex shrink-0 items-center border-r border-slate-800 ${activePath === tab.path ? 'bg-slate-800' : ''}`}><button role="tab" aria-selected={activePath === tab.path} onClick={() => setActivePath(tab.path)} className="px-3 py-3 text-xs">{tab.path}{dirty(tab) ? ' • Unsaved' : ''}</button><button aria-label={`Close ${tab.path}`} disabled={busy} onClick={() => closeTab(tab)} className="px-3 py-2 text-slate-400 hover:text-white">×</button></div>)}</div>
          {active?.latest && <div className="space-y-2 border-b border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-100"><p>The saved file changed. Compare the latest saved version (left) with your edits (right).</p><div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !workspace.can_edit || !!active.latest.read_only_reason} onClick={() => void saveFile(true)}>Save reviewed version</button><button className={button} disabled={busy} onClick={() => { if (window.confirm('Discard your edits and reload the latest saved file?')) changeTabs(current => current.map(tab => tab.path === active.path && tab.latest ? openTab(tab.latest) : tab)); }}>Reload latest</button></div></div>}
          {active?.read_only_reason && <p className="p-4 text-sm text-amber-200">{active.read_only_reason}</p>}
          <div className="min-h-0 flex-1">{active ? active.latest ? <DiffEditor key={`${workspace.id}:${active.path}:conflict`} height="100%" language={monacoLanguage(active.path)} original={active.latest.content ?? ''} modified={active.content} theme="vs-dark" options={{ readOnly: true, originalEditable: false, renderSideBySide: true, minimap: { enabled: false } }} /> : <Editor height="100%" path={`${workspace.id}/${active.path}`} language={monacoLanguage(active.path)} value={active.content} theme="vs-dark" onChange={value => { const content = value ?? ''; changeTabs(current => current.map(tab => tab.path === active.path ? { ...tab, content } : tab)); }} options={{ readOnly: !!active.read_only_reason || !workspace.can_edit, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }} /> : <div className="grid h-full min-h-48 place-items-center p-6 text-sm text-slate-400">Open a file to begin editing. Saves preserve its encoding and line endings.</div>}</div>
          {active && <footer className="border-t border-slate-800 px-3 py-2 text-xs text-slate-400">{active.encoding} · {active.newline.toUpperCase()} · {dirty(active) ? 'Unsaved changes' : 'Saved'} · Ctrl/Cmd+S to save</footer>}
        </main>
      </div>
    </>}
  </div>;
}
