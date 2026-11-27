'use client';

import { useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { fileLineHref } from '@/lib/code';

export type Citation = {
  number: number;
  chunk_id: string;
  source?: string;
  document_name?: string;
  label?: string;
  pages?: number[];
  sections?: string[];
  repository_id?: string;
  file_path?: string;
  start_line?: number;
  end_line?: number;
  url?: string;
  title?: string;
  domain?: string;
  snippet?: string;
};

function safeWebUrl(value?: string): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function Citations({ citations }: { citations: Citation[] }) {
  const [source, setSource] = useState('');
  return (
    <div className="mt-3 border-t pt-2 text-sm">
      <p className="font-medium">Retrieved sources</p>
      {citations.map(c => {
        if (c.source === 'code' && c.repository_id && c.file_path) {
          return (
            <Link key={`${c.number}-${c.chunk_id}`} className="mt-1 block text-left underline" href={fileLineHref(c.repository_id, c.file_path, c.start_line)}>
              [{c.number}] {c.label || c.file_path} · lines {c.start_line}-{c.end_line}
            </Link>
          );
        }
        if (c.source === 'web') {
          const href = safeWebUrl(c.url);
          const label = c.title || c.label || c.domain || 'Web source';
          return (
            <div key={`${c.number}-${c.chunk_id}`} className="mt-1 flex flex-wrap items-center gap-2">
              {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-left underline">
                  [{c.number}] {label}{c.domain ? ` (${c.domain})` : ''}
                </a>
              ) : (
                <span>[{c.number}] {label}</span>
              )}
              {c.snippet && (
                <button type="button" className="text-xs text-slate-500 underline" onClick={() => setSource(c.snippet || '')}>
                  Excerpt
                </button>
              )}
            </div>
          );
        }
        return (
          <button
            key={`${c.number}-${c.chunk_id}`}
            className="block text-left underline mt-1"
            onClick={async () => {
              try {
                const chunk = await api<{ content: string }>(`/chunks/${c.chunk_id}`);
                setSource(chunk.content);
              } catch (e) {
                setSource((e as Error).message);
              }
            }}
          >
            [{c.number}] {c.document_name || c.label || 'Source'}
            {c.pages?.length ? ` · page ${c.pages.join(', ')}` : ''}
            {c.sections?.length ? ` · ${c.sections.join(' / ')}` : ''}
          </button>
        );
      })}
      {source && (
        <div className="mt-3 p-3 border rounded whitespace-pre-wrap">
          <button className="block underline mb-2" onClick={() => setSource('')}>Close excerpt</button>
          {source}
        </div>
      )}
    </div>
  );
}
