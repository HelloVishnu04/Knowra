'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { fileLineHref } from '@/lib/code';
import { formatScore, humanizeStage, RunDetail } from '@/lib/runs';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => <div className="grid h-96 place-items-center rounded-lg bg-slate-950 text-sm text-slate-400">Loading patch review…</div>,
});

function JsonValue({ value }: { value: unknown }) {
  return <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(value, null, 2)}</pre>;
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editingTool, setEditingTool] = useState('');
  const [editedPatch, setEditedPatch] = useState('');

  const refresh = useCallback(() => api<RunDetail>(`/runs/${runId}`)
    .then(value => { setRun(value); setError(''); })
    .catch(reason => setError((reason as Error).message)), [runId]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  const decide = async (action: 'approve' | 'edit' | 'reject', patch?: string) => {
    setBusy(true);
    try {
      const value = await api<RunDetail>(`/runs/${runId}/approval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, patch }),
      });
      setRun(value);
      setEditingTool('');
      setEditedPatch('');
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!run) return <div className="p-10 text-sm text-slate-500">{error || 'Loading run trace…'}</div>;

  const sqlQueries = Array.from(new Set([
    ...run.trace.map(step => step.details.sql).filter((value): value is string => typeof value === 'string'),
    ...run.tool_calls.map(tool => tool.arguments.sql).filter((value): value is string => typeof value === 'string'),
  ]));

  return <div className="h-full overflow-y-auto bg-slate-50 p-6 sm:p-10">
    <div className="mx-auto max-w-6xl space-y-8">
      <div>
        <Link href="/runs" className="text-sm text-slate-500 hover:text-slate-900">← All runs</Link>
        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-xs text-slate-400">{run.id}</p>
            <h1 className="mt-2 max-w-3xl text-2xl font-semibold text-slate-950">{run.user_query}</h1>
          </div>
          <div className="flex gap-2 text-xs">
            <span className="rounded-full bg-slate-900 px-3 py-1.5 text-white">{humanizeStage(run.route)}</span>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-slate-700">{humanizeStage(run.status)}</span>
          </div>
        </div>
        <p className="mt-3 text-sm text-slate-500">{run.provider} · {run.model} · {run.planned_routes.length ? run.planned_routes.join(' + ') : 'no retrieval'}</p>
      </div>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {run.error && <p className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{run.error}</p>}

      {!!sqlQueries.length && <section className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-slate-900">Generated SQL</h2>
          <span className="rounded-full bg-cyan-100 px-2.5 py-1 text-xs font-medium text-cyan-800">Read-only · row-limited · timed</span>
        </div>
        <div className="mt-4 space-y-3">{sqlQueries.map(sql => <pre key={sql} className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-xs leading-5 text-cyan-100">{sql}</pre>)}</div>
      </section>}

      <section>
        <h2 className="text-lg font-semibold text-slate-900">Execution timeline</h2>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {run.trace.map((step, index) => <article key={`${step.node}-${index}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-medium text-slate-900">{index + 1}. {humanizeStage(step.node)}</h3>
              <span className="text-xs font-medium text-slate-500">{humanizeStage(step.status)}</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">{new Date(step.at).toLocaleString()}</p>
            <JsonValue value={step.details} />
          </article>)}
        </div>
      </section>

      {!!run.coding_attempts.length && <section>
        <h2 className="text-lg font-semibold text-slate-900">Coding attempts</h2>
        <div className="mt-4 grid gap-3 lg:grid-cols-3">{run.coding_attempts.map(attempt => <article key={attempt.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3"><strong>Attempt {attempt.attempt}</strong><span className={`rounded-full px-2 py-1 text-xs ${attempt.status === 'ready_for_review' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>{humanizeStage(attempt.status)}</span></div>
          <p className="mt-3 line-clamp-3 text-sm text-slate-600">{attempt.plan}</p>
          <div className="mt-3 space-y-2">{attempt.checks.map((check, index) => <div key={`${check.stage}-${index}`} className="rounded-lg bg-slate-50 p-2 text-xs"><div className="flex justify-between gap-2"><span className="font-medium">{humanizeStage(check.stage)}</span><span>{humanizeStage(check.status)}</span></div><p className="mt-1 truncate font-mono text-slate-500">{check.command}</p></div>)}</div>
          {attempt.error && <p className="mt-3 text-xs text-red-600">{attempt.error}</p>}
        </article>)}</div>
      </section>}

      {!!run.execution_jobs.length && <section>
        <div className="flex items-end justify-between gap-4"><div><h2 className="text-lg font-semibold text-slate-900">Sandbox execution</h2><p className="mt-1 text-sm text-slate-500">Disposable, network-disabled containers. Output refreshes while each job runs.</p></div><span className="rounded-full bg-slate-200 px-2.5 py-1 text-xs text-slate-700">{run.execution_jobs.length} jobs</span></div>
        <div className="mt-4 space-y-3">{run.execution_jobs.map(job => <article key={job.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><strong>{humanizeStage(job.stage)}</strong><p className="mt-1 font-mono text-xs text-slate-500">{job.command.join(' ')}</p></div><span className={`rounded-full px-2.5 py-1 text-xs ${job.status === 'passed' ? 'bg-emerald-100 text-emerald-800' : job.status === 'failed' || job.status === 'timed_out' ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'}`}>{humanizeStage(job.status)}</span></div>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500"><span>Attempt {job.attempt}</span><span>{job.image}</span><span>{job.duration_ms == null ? 'Running…' : `${job.duration_ms} ms`}</span><span>Exit {job.exit_code ?? '—'}</span></div>
          {(job.stdout || job.stderr || job.error) && <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">{[job.stdout, job.stderr, job.error].filter(Boolean).join('\n')}</pre>}
        </article>)}</div>
      </section>}

      <section>
        <h2 className="text-lg font-semibold text-slate-900">Retrievals</h2>
        <div className="mt-4 space-y-4">
          {run.retrievals.map(retrieval => <article key={retrieval.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-medium text-slate-900">{humanizeStage(retrieval.source)}</h3>
              <p className="text-xs text-slate-500">{retrieval.result_count} results · {retrieval.latency_ms} ms · {retrieval.status}</p>
            </div>
            {retrieval.error && <p className="mt-3 text-sm text-red-600">{retrieval.error}</p>}
            <div className="mt-4 space-y-2">
              {retrieval.chunks.map(chunk => <div key={chunk.id} className="rounded-lg bg-slate-50 p-3 text-sm">
                <div className="flex justify-between gap-3 font-mono text-xs text-slate-500"><span className="truncate">{chunk.id}</span><span>{formatScore(chunk.score)}</span></div>
                <p className="mt-2 text-slate-700">{chunk.preview}</p>
              </div>)}
            </div>
          </article>)}
          {!run.retrievals.length && <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500">This was a direct model route with no retrieval step.</p>}
        </div>
      </section>

      {!!run.citations.length && <section>
        <h2 className="text-lg font-semibold text-slate-900">Citations</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">{run.citations.map(citation => {
          const codeHref = citation.source === 'code' && typeof citation.repository_id === 'string' && typeof citation.file_path === 'string'
            ? fileLineHref(citation.repository_id, citation.file_path, typeof citation.start_line === 'number' ? citation.start_line : 1)
            : null;
          return <article key={`${citation.source}-${citation.number}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <strong className="text-sm text-slate-900">[{citation.number}] {citation.label}</strong>
            <span className="text-xs text-slate-500">{humanizeStage(citation.source)}</span>
          </div>
          <p className="mt-2 break-all font-mono text-xs text-slate-400">{String(citation.chunk_id ?? 'No chunk id')}</p>
          {codeHref && <Link href={codeHref} className="mt-3 inline-block text-xs font-medium text-cyan-700 underline">Open file at line {String(citation.start_line ?? 1)} →</Link>}
        </article>})}</div>
      </section>}

      {!!run.tool_calls.length && <section>
        <h2 className="text-lg font-semibold text-slate-900">Tool approvals</h2>
        <div className="mt-4 space-y-3">{run.tool_calls.map(tool => <article key={tool.id} className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex flex-wrap justify-between gap-3"><strong>{tool.name}</strong><span className="text-sm">{humanizeStage(tool.status)}</span></div>
          {tool.name === 'create_patch' && typeof tool.arguments.patch === 'string' ? <div className="mt-4 space-y-4">
            <div className="grid gap-3 rounded-lg bg-slate-50 p-4 text-sm md:grid-cols-[1fr_2fr]"><div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Files</p><p className="mt-1 font-mono text-xs text-slate-700">{Array.isArray(tool.arguments.changed_files) ? tool.arguments.changed_files.join(', ') : '—'}</p></div><div><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Plan</p><p className="mt-1 whitespace-pre-wrap text-slate-700">{String(tool.arguments.plan ?? '')}</p></div></div>
            <MonacoEditor height="420px" language="diff" theme="vs-dark" value={editingTool === tool.id ? editedPatch : tool.arguments.patch} onChange={value => { if (editingTool === tool.id) setEditedPatch(value ?? ''); }} options={{ readOnly: editingTool !== tool.id, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, wordWrap: 'on' }} />
            {Boolean(tool.arguments.checks_invalidated_by_edit) && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">The reviewer changed this diff after automated checks; those check results no longer apply.</p>}
            {tool.status === 'pending' && editingTool !== tool.id && <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={() => void decide('approve')} className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">Approve patch</button>
              <button disabled={busy} onClick={() => { setEditingTool(tool.id); setEditedPatch(String(tool.arguments.patch)); }} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Edit patch</button>
              <button disabled={busy} onClick={() => void decide('reject')} className="rounded-lg border border-red-200 px-4 py-2 text-sm text-red-700 disabled:opacity-50">Reject</button>
            </div>}
            {tool.status === 'pending' && editingTool === tool.id && <div className="flex flex-wrap gap-2">
              <button disabled={busy || !editedPatch.trim()} onClick={() => void decide('edit', editedPatch)} className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">Save edit & approve</button>
              <button disabled={busy} onClick={() => { setEditingTool(''); setEditedPatch(''); }} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Cancel edit</button>
            </div>}
          </div> : <>
            <JsonValue value={tool.arguments} />
            {tool.status === 'pending' && <div className="mt-4 flex gap-2">
              <button disabled={busy} onClick={() => void decide('approve')} className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">Approve</button>
              <button disabled={busy} onClick={() => void decide('reject')} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Reject</button>
            </div>}
          </>}
        </article>)}</div>
      </section>}

      {run.answer && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Generated answer</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{run.answer}</p>
      </section>}
    </div>
  </div>;
}
