import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatStreamDecoder } from '../src/lib/sse.ts';

test('preserves citation and text events at every byte boundary', () => {
  const events = [{ citations: [{ chunk_id: 'chunk-1', pages: [2] }] }, { content: 'Résumé 文' }];
  const bytes = new TextEncoder().encode(events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n');
  for (let boundary = 0; boundary <= bytes.length; boundary++) {
    const decoder = new ChatStreamDecoder();
    const result = [...decoder.push(bytes.slice(0, boundary)), ...decoder.push(bytes.slice(boundary))];
    assert.deepEqual(result, [...events.map(e => JSON.stringify(e)), '[DONE]']);
  }
});

test('retains server error payloads', () => {
  const decoder = new ChatStreamDecoder();
  assert.deepEqual(decoder.push(new TextEncoder().encode('event: error\ndata: {"error":"failed"}\n\n')), ['{"error":"failed"}']);
});
