'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

type KB = { id: string; name: string; description: string };
type Document = { id: string; name: string; status: string; error?: string };

export default function KnowledgePage() {
  const [bases, setBases] = useState<KB[]>([]);
  const [selected, setSelected] = useState('');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api<KB[]>('/knowledge-bases').then(value => { if (active) setBases(value); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    const refresh = () => api<Document[]>(`/knowledge-bases/${selected}/documents`)
      .then(value => { if (active) setDocuments(value); })
      .catch(e => { if (active) setError(e.message); });
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [selected]);

  return <div className="overflow-y-auto p-8 space-y-6 max-w-5xl w-full mx-auto">
    <div><h1 className="text-2xl font-semibold">Knowledge bases</h1>
      <p className="text-sm text-gray-500 mt-2">Upload documents to your local workspace, then ask questions with source citations.</p></div>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    <form className="flex gap-3" onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError('');
      try {
        const kb = await api<KB>('/knowledge-bases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
        setBases(prev => [kb, ...prev]); setSelected(kb.id); setDocuments([]); setName('');
      } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>
      <input aria-label="Knowledge base name" required maxLength={120} value={name} onChange={e => setName(e.target.value)} placeholder="Knowledge base name" className="border rounded p-2 flex-1" />
      <button disabled={busy || !name.trim()} className="border rounded px-4 disabled:opacity-50">Create knowledge base</button>
    </form>
    <label className="block">Select knowledge base
      <select className="border rounded p-2 ml-3" value={selected} onChange={e => { setSelected(e.target.value); setDocuments([]); }}>
        <option value="">Choose a knowledge base</option>
        {bases.map(kb => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
      </select>
    </label>
    {selected && <>
      <form className="border rounded-lg p-5 space-y-3" onSubmit={async e => {
        e.preventDefault(); const form = e.currentTarget;
        setBusy(true); setError('');
        try {
          const doc = await api<Document>(`/knowledge-bases/${selected}/documents`, { method: 'POST', body: new FormData(form) });
          setDocuments(prev => [doc, ...prev.filter(d => d.id !== doc.id)]); form.reset();
        } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>
        <label className="block">Document (PDF, DOCX, PPTX, XLSX; up to 25 MB)
          <input required name="file" type="file" accept=".pdf,.docx,.pptx,.xlsx" className="block mt-3" /></label>
        <button disabled={busy} className="border rounded px-4 py-2 disabled:opacity-50">{busy ? 'Working…' : 'Upload and index'}</button>
      </form>
      <Link className="underline inline-block" href={`/chat?kb=${selected}`}>Ask questions about this knowledge base →</Link>
      <ul className="space-y-3" aria-live="polite">{documents.map(doc => <li key={doc.id} className="border rounded-lg p-4">
        <div className="flex justify-between gap-4"><strong>{doc.name}</strong><span>{doc.status}</span></div>
        {doc.error && <p className="text-red-600 text-sm mt-2">{doc.error}</p>}
        {doc.status === 'failed' && <button disabled={busy} className="underline mt-2" onClick={async () => {
          setBusy(true); setError('');
          try { const updated = await api<Document>(`/knowledge-bases/${selected}/documents/${doc.id}/retry`, { method: 'POST' }); setDocuments(prev => prev.map(d => d.id === doc.id ? updated : d)); }
          catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>Retry indexing</button>}
      </li>)}</ul>
      {documents.length === 0 && <p className="text-gray-500">No documents yet.</p>}
    </>}
  </div>;
}
