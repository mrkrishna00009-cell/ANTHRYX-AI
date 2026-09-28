import { describe, it, expect, beforeEach } from 'vitest';
import 'fake-indexeddb/auto';
import { queueEvidence, countPending, markSynced, listPending, newClientUuid, SYNC_STATUS } from '../db.js';

describe('offline queue (M2)', () => {
  it('generates a valid client UUID', () => {
    const uuid = newClientUuid();
    expect(uuid).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('queues a record as PENDING_SYNC and it counts toward pending', async () => {
    const before = await countPending();
    const row = await queueEvidence({ kind: 'INCIDENT', payload: { mine_id: 'm1' } });
    expect(row.sync_status).toBe(SYNC_STATUS.PENDING);
    const after = await countPending();
    expect(after).toBe(before + 1);
  });

  it('re-queuing the SAME client_uuid does not create a duplicate (idempotent key)', async () => {
    const uuid = newClientUuid();
    await queueEvidence({ client_uuid: uuid, kind: 'INCIDENT', payload: { mine_id: 'm1' } });
    const before = await countPending();
    await queueEvidence({ client_uuid: uuid, kind: 'INCIDENT', payload: { mine_id: 'm1', notes: 'updated' } });
    const after = await countPending();
    expect(after).toBe(before); // same key overwrites, does not add a second pending row
  });

  it('marking a record synced removes it from the pending count', async () => {
    const row = await queueEvidence({ kind: 'ATTENDANCE', payload: { mine_id: 'm2' } });
    const beforeSync = await countPending();
    await markSynced(row.client_uuid);
    const afterSync = await countPending();
    expect(afterSync).toBe(beforeSync - 1);
    const pending = await listPending();
    expect(pending.find((r) => r.client_uuid === row.client_uuid)).toBeUndefined();
  });
});
