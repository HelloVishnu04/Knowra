import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatScore, traceStages } from '../src/lib/runs.ts';

test('builds readable rows for the run trace UI', () => {
  const stages = traceStages({
    trace: [
      { node: 'plan_route', status: 'completed', at: '2026-01-01', details: {} },
      { node: 'fuse_rerank', status: 'fallback', at: '2026-01-01', details: {} },
    ],
  });
  assert.deepEqual(stages, ['Plan Route · completed', 'Fuse Rerank · fallback']);
  assert.equal(formatScore(0.012345), '0.0123');
});
