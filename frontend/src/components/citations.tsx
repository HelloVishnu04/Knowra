'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

export type Citation = { number: number; chunk_id: string; document_name: string; pages: number[]; sections: string[] };

export function Citations({ citations }: { citations: Citation[] }) {
  const [source, setSource] = useState('');
  return <div className="mt-3 border-t pt-2 text-sm">
    <p className="font-medium">Retrieved sources</p>
    {citations.map(c => <button key={c.chunk_id} className="block text-left underline mt-1" onClick={async () => {
      try { const chunk = await api<{ content: string }>(`/chunks/${c.chunk_id}`); setSource(chunk.content); }
      catch (e) { setSource((e as Error).message); }
    }}>[{c.number}] {c.document_name}{c.pages.length ? ` · page ${c.pages.join(', ')}` : ''}{c.sections.length ? ` · ${c.sections.join(' / ')}` : ''}</button>)}
    {source && <div className="mt-3 p-3 border rounded whitespace-pre-wrap"><button className="block underline mb-2" onClick={() => setSource('')}>Close excerpt</button>{source}</div>}
  </div>;
}
