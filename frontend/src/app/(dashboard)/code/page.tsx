'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { OnMount } from '@monaco-editor/react';
import { api } from '@/lib/api';
import { CodeFile, CodeReference, CodeSymbol, monacoLanguage, Repository, TreeEntry } from '@/lib/code';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => <div className="grid h-full place-items-center bg-slate-950 text-sm text-slate-400">Loading code editor…</div>,
});

function Status({ value }: { value: string }) {
  const tone = value === 'ready' ? 'bg-emerald-100 text-emerald-800' : value === 'failed' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{value.replaceAll('_', ' ')}</span>;
}

export default function CodeWorkspacePage() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repositoryId, setRepositoryId] = useState(() => typeof window === 'undefined' ? '' : new URLSearchParams(window.location.search).get('repository') || '');
  const [tree, setTree] = useState<TreeEntry[]>([]);
  const [file, setFile] = useState<CodeFile | null>(null);
  const [targetLine, setTargetLine] = useState(1);
  const [query, setQuery] = useState('');
  const [symbols, setSymbols] = useState<CodeSymbol[]>([]);
  const [references, setReferences] = useState<CodeReference[]>([]);
  const [diff, setDiff] = useState('');
  const [gitUrl, setGitUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refreshRepositories = useCallback(() => api<Repository[]>('/repositories').then(items => {
    setRepositories(items);
    setRepositoryId(current => current || items[0]?.id || '');
  }).catch(reason => setError((reason as Error).message)), []);

  useEffect(() => {
    void refreshRepositories();
    const timer = setInterval(refreshRepositories, 4000);
    return () => clearInterval(timer);
  }, [refreshRepositories]);

  const openFile = useCallback(async (path: string, line = 1) => {
    if (!repositoryId) return;
    try {
      const value = await api<CodeFile>(`/repositories/${repositoryId}/file?path=${encodeURIComponent(path)}&start=1&end=10000`);
      setFile(value);
      setTargetLine(line);
      setError('');
      const url = new URL(window.location.href);
      url.searchParams.set('repository', repositoryId);
      url.searchParams.set('path', path);
      url.searchParams.set('line', String(line));
      window.history.replaceState(null, '', url);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, [repositoryId]);

  useEffect(() => {
    if (!repositoryId) return;
    const treeRequest = api<TreeEntry[]>(`/repositories/${repositoryId}/tree`);
    void treeRequest.then(setTree).catch(reason => setError((reason as Error).message));
    const params = new URLSearchParams(window.location.search);
    const path = params.get('path');
    const line = Number(params.get('line') || 1);
    if (path && params.get('repository') === repositoryId) void treeRequest.then(() => openFile(path, line));
  }, [repositoryId, openFile]);

  useEffect(() => {
    if (!repositoryId) return;
    const timer = setTimeout(() => {
      api<CodeSymbol[]>(`/repositories/${repositoryId}/symbols?q=${encodeURIComponent(query)}`).then(setSymbols).catch(reason => setError((reason as Error).message));
    }, 180);
    return () => clearTimeout(timer);
  }, [repositoryId, query]);

  const selectedRepository = repositories.find(item => item.id === repositoryId);
  const files = useMemo(() => tree.filter(item => item.type === 'file'), [tree]);

  const editorMount: OnMount = editor => {
    editor.revealLineInCenter(targetLine);
    editor.setPosition({ lineNumber: targetLine, column: 1 });
  };

  const uploadZip = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('archive') as HTMLInputElement;
    if (!input.files?.[0]) return;
    setBusy(true);
    try {
      const body = new FormData();
      body.append('file', input.files[0]);
      const created = await api<{ id: string }>('/repositories/zip', { method: 'POST', body });
      setRepositoryId(created.id);
      input.value = '';
      await refreshRepositories();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  };

  const addGit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!gitUrl.trim()) return;
    setBusy(true);
    try {
      const created = await api<{ id: string }>('/repositories/git', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: gitUrl }) });
      setRepositoryId(created.id);
      setGitUrl('');
      await refreshRepositories();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  };

  const showReferences = async (symbol: CodeSymbol) => {
    setReferences(await api<CodeReference[]>(`/repositories/${repositoryId}/references?symbol=${encodeURIComponent(symbol.name)}`));
    await openFile(symbol.file_path, symbol.start_line);
  };

  const showDiff = async () => {
    const value = await api<{ diff: string; message: string }>(`/repositories/${repositoryId}/diff`);
    setDiff(value.diff || value.message);
  };

  return <div className="flex h-full min-h-0 flex-col bg-slate-950 text-slate-100">
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-900 px-4 py-3">
      <div className="mr-auto"><h1 className="font-semibold">Code Workspace</h1><p className="text-xs text-slate-400">Tree-sitter symbols, references, and repository-scoped search</p></div>
      <select aria-label="Repository" value={repositoryId} onChange={event => { setRepositoryId(event.target.value); if (!event.target.value) setTree([]); }} className="max-w-64 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
        <option value="">Select repository</option>{repositories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      {selectedRepository && <Status value={selectedRepository.status} />}
      <button disabled={!repositoryId} onClick={() => void showDiff()} className="rounded-md border border-slate-700 px-3 py-2 text-xs disabled:opacity-40">Git diff</button>
    </header>

    {!repositories.length && <div className="grid flex-1 place-items-center p-6"><div className="w-full max-w-xl space-y-5 rounded-2xl border border-slate-800 bg-slate-900 p-6"><div><h2 className="text-xl font-semibold">Index a repository</h2><p className="mt-1 text-sm text-slate-400">Upload a ZIP or clone from an allowed HTTPS Git host.</p></div><form onSubmit={uploadZip} className="flex gap-2"><input name="archive" type="file" accept=".zip" className="min-w-0 flex-1 rounded border border-slate-700 p-2 text-sm"/><button disabled={busy} className="rounded bg-cyan-500 px-4 text-sm font-semibold text-slate-950">Upload</button></form><form onSubmit={addGit} className="flex gap-2"><input value={gitUrl} onChange={event => setGitUrl(event.target.value)} placeholder="https://github.com/org/repo.git" className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"/><button disabled={busy} className="rounded border border-slate-600 px-4 text-sm">Clone</button></form></div></div>}

    {!!repositories.length && <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)_320px]">
      <aside className="min-h-0 overflow-y-auto border-r border-slate-800 bg-slate-900 p-3"><div className="mb-3 flex items-center justify-between"><h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Repository tree</h2><span className="text-xs text-slate-500">{files.length} files</span></div>{selectedRepository?.error && <p className="mb-3 rounded bg-red-950 p-2 text-xs text-red-300">{selectedRepository.error}</p>}{files.map(item => <button key={item.path} title={item.path} onClick={() => void openFile(item.path)} className={`block w-full truncate rounded px-2 py-1.5 text-left font-mono text-xs hover:bg-slate-800 ${file?.path === item.path ? 'bg-cyan-950 text-cyan-300' : 'text-slate-300'}`}>{item.path}</button>)}</aside>
      <main className="min-h-0"><div className="flex h-10 items-center border-b border-slate-800 px-3 font-mono text-xs text-slate-400">{file ? `${file.path}:${targetLine}` : 'Select a source file'}</div><div className="h-[calc(100%-2.5rem)]">{file ? <Editor height="100%" path={file.path} language={monacoLanguage(file.path)} value={file.content} theme="vs-dark" onMount={editorMount} options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }} /> : <div className="grid h-full place-items-center text-sm text-slate-500">Choose a file or symbol to inspect it.</div>}</div></main>
      <aside className="min-h-0 overflow-y-auto border-l border-slate-800 bg-slate-900 p-4"><h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Symbol search</h2><input value={query} onChange={event => setQuery(event.target.value)} placeholder="JWT validation" className="mt-3 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm"/><div className="mt-3 space-y-2">{symbols.map(symbol => <button key={symbol.id} onClick={() => void showReferences(symbol)} className="w-full rounded-lg border border-slate-800 p-3 text-left hover:border-cyan-800"><div className="flex justify-between gap-2"><strong className="truncate text-sm text-slate-200">{symbol.name}</strong><span className="text-[10px] uppercase text-cyan-400">{symbol.kind}</span></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{symbol.file_path}:{symbol.start_line}</p></button>)}</div>{!!references.length && <div className="mt-6"><h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">References</h2><div className="mt-2 space-y-2">{references.map(reference => <button key={reference.id} onClick={() => void openFile(reference.file_path, reference.line)} className="block w-full rounded bg-slate-950 p-2 text-left font-mono text-xs text-slate-400 hover:text-cyan-300">{reference.file_path}:{reference.line}<span className="mt-1 block truncate text-slate-600">{reference.text}</span></button>)}</div></div>}{diff && <div className="mt-6"><div className="flex justify-between"><h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Git diff</h2><button onClick={() => setDiff('')} className="text-xs text-slate-500">Close</button></div><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-black p-3 text-[11px] text-emerald-300">{diff}</pre></div>}</aside>
    </div>}
    {error && <div role="alert" className="border-t border-red-900 bg-red-950 px-4 py-2 text-xs text-red-300">{error}<button onClick={() => setError('')} className="ml-3 underline">Dismiss</button></div>}
  </div>;
}
