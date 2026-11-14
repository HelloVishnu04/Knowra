import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileLineHref, monacoLanguage } from '../src/lib/code.ts';

test('builds repository file and line navigation links', () => {
  assert.equal(
    fileLineHref('repo 1', 'src/auth token.ts', 42),
    '/code?repository=repo+1&path=src%2Fauth+token.ts&line=42',
  );
  assert.equal(monacoLanguage('src/auth.ts'), 'typescript');
  assert.equal(monacoLanguage('backend/auth.py'), 'python');
});
