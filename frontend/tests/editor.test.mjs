import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dirty, openTab, savedTab, parseDraft, draftKey } from '../src/lib/editor.ts';

const file = { path: 'hello.py', content: 'original\n', version: 'a'.repeat(64), encoding: 'utf-8', newline: 'crlf', revision: 0, size: 10, read_only_reason: null };

test('a stale recovery draft requires review against the latest file', () => {
  const tab = openTab(file, { content: 'my edit\n', version: 'b'.repeat(64), savedAt: 1 });
  assert.equal(tab.latest, file);
  assert.equal(tab.content, 'my edit\n');
  assert.equal(tab.version, 'b'.repeat(64));
  assert.equal(dirty(tab), true);
});

test('save acknowledgement preserves typing that happened during the request', () => {
  const tab = { ...openTab(file), content: 'typed after save' };
  const result = savedTab(tab, 'submitted text', { ...file, version: 'c'.repeat(64), revision: 1 });
  assert.equal(result.content, 'typed after save');
  assert.equal(result.original, 'submitted text');
  assert.equal(result.version, 'c'.repeat(64));
  assert.equal(dirty(result), true);
});

test('drafts are scoped to a working copy and validated before restoration', () => {
  assert.notEqual(draftKey('alice-copy', 'a.ts'), draftKey('bob-copy', 'a.ts'));
  assert.equal(parseDraft('{invalid'), null);
  assert.equal(parseDraft(JSON.stringify({ content: [], version: null, savedAt: 1 })), null);
  assert.equal(parseDraft(JSON.stringify({ content: '', version: null, savedAt: 1, isNew: true })).isNew, true);
  assert.equal(dirty({ ...openTab(file), content: '', original: '', isNew: true }), true);
  assert.equal(openTab({ ...file, read_only_reason: 'Binary' }, { content: 'unsafe', version: null, savedAt: 1 }).content, file.content);
});
