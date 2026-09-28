import { describe, it, expect, vi } from 'vitest';
import 'fake-indexeddb/auto';
import { queueEvidence } from '../db.js';
import { flushQueue } from '../sync.js';

describe('sync queue flush (M2)', () => {
  it('posts each pending record and marks successes synced', async () => {
    await queueEvidence({ kind: 'INCIDENT', payload: { mine_id: 'm1', notes: 'test' } });
    const postImpl = vi.fn().mockResolvedValue({ ok: true });

    const result = await flushQueue({ postImpl });

    expect(result.attempted).toBeGreaterThanOrEqual(1);
    expect(result.synced).toBe(result.attempted);
    expect(postImpl).toHaveBeenCalled();
  });

  it('leaves a record PENDING when the server rejects it, rather than dropping it', async () => {
    await queueEvidence({ kind: 'INCIDENT', payload: { mine_id: 'm1' } });
    const postImpl = vi.fn().mockResolvedValue({ ok: false, status: 401 });

    const result = await flushQueue({ postImpl });

    expect(result.synced).toBe(0);
    expect(result.failures.length).toBeGreaterThanOrEqual(1);
  });

  it('a network error during flush does not throw, and leaves the record pending', async () => {
    await queueEvidence({ kind: 'INCIDENT', payload: { mine_id: 'm1' } });
    const postImpl = vi.fn().mockRejectedValue(new Error('network down'));

    const result = await flushQueue({ postImpl });

    expect(result.synced).toBe(0);
    expect(result.failures[0].error).toContain('network down');
  });
});
