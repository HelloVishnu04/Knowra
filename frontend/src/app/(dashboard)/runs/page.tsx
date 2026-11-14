'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { humanizeStage, RunSummary } from '@/lib/runs';

function StatusPill({ value }: { value: string }) {
  const tone = value === 'completed'
    ? 'bg-emerald-100 text-emerald-800'
    : value === 'failed'
      ? 'bg-red-100 text-red-800'
      : value === 'pending_approval'
        ? 'bg-amber-100 text-amber-800'
        : 'bg-blue-100 text-blue-800';
  return <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>{humanizeStage(value)}</span>;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const refresh = () => api<RunSummary[]>('/runs')
      .then(value => { if (active) { setRuns(value); setError(''); } })
      .catch(reason => { if (active) setError((reason as Error).message); });
    void refresh();
    const timer = setInterval(refresh, 4000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  return <div className="h-full overflow-y-auto bg-slate-50 p-6 sm:p-10">
    <div className="mx-auto max-w-6xl space-y-7">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Observability</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Runs & traces</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">Inspect every route decision, retrieval, rerank score, model call, citation, and approval state.</p>
      </div>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {runs.map(run => <Link key={run.id} href={`/runs/${run.id}`} className="grid gap-3 border-b border-slate-100 p-5 transition hover:bg-slate-50 last:border-0 md:grid-cols-[minmax(0,1fr)_160px_140px_180px] md:items-center">
          <div className="min-w-0">
            <p className="truncate font-medium text-slate-900">{run.query_preview}</p>
            <p className="mt-1 truncate font-mono text-xs text-slate-400">{run.id}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Route</p>
            <p className="mt-1 text-sm font-medium text-slate-700">{humanizeStage(run.route)}</p>
          </div>
          <StatusPill value={run.status} />
          <div className="text-sm text-slate-500 md:text-right">
            {run.created_at ? new Date(run.created_at).toLocaleString() : 'Starting…'}
          </div>
        </Link>)}
        {!runs.length && !error && <div className="p-12 text-center text-sm text-slate-500">No agent runs yet. Start a chat to create the first trace.</div>}
      </div>
    </div>
  </div>;
}
