/**
 * IndexedDB access for offline field evidence (M2).
 *
 * Phase 1 establishes the store shape and the pending-sync queue only.
 * Inspection, attendance and incident forms are implemented in Phase 6.
 *
 * Records are keyed by a client-generated UUID so a retried sync cannot
 * create a duplicate server-side. The client clock is recorded for
 * comparison only; the server timestamp is authoritative.
 */

import { openDB } from 'idb';

export const DB_NAME = 'anthryx-field';
export const DB_VERSION = 1;
export const STORE_EVIDENCE = 'field_evidence';
export const STORE_PHOTOS = 'photo_blobs';

export const SYNC_STATUS = {
  PENDING: 'PENDING_SYNC',
  IN_FLIGHT: 'IN_FLIGHT',
  SYNCED: 'SYNCED',
  FAILED: 'FAILED',
};

export const EVIDENCE_KIND = {
  INSPECTION: 'INSPECTION',
  ATTENDANCE: 'ATTENDANCE',
  INCIDENT: 'INCIDENT',
};

export function newClientUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  // Fallback for older browsers; still collision-safe enough for a queue key.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function getDb() {
  return openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE_EVIDENCE)) {
        const store = db.createObjectStore(STORE_EVIDENCE, { keyPath: 'client_uuid' });
        store.createIndex('by_sync_status', 'sync_status');
        store.createIndex('by_kind', 'kind');
      }
      if (!db.objectStoreNames.contains(STORE_PHOTOS)) {
        db.createObjectStore(STORE_PHOTOS, { keyPath: 'client_uuid' });
      }
    },
  });
}

export async function countPending() {
  const db = await getDb();
  return db.countFromIndex(STORE_EVIDENCE, 'by_sync_status', SYNC_STATUS.PENDING);
}

export async function listPending() {
  const db = await getDb();
  return db.getAllFromIndex(STORE_EVIDENCE, 'by_sync_status', SYNC_STATUS.PENDING);
}

export async function queueEvidence(record) {
  const db = await getDb();
  const row = {
    client_uuid: record.client_uuid ?? newClientUuid(),
    kind: record.kind,
    payload: record.payload ?? {},
    client_timestamp: new Date().toISOString(),
    sync_status: SYNC_STATUS.PENDING,
    attempts: 0,
  };
  await db.put(STORE_EVIDENCE, row);
  return row;
}

export async function markSynced(clientUuid) {
  const db = await getDb();
  const row = await db.get(STORE_EVIDENCE, clientUuid);
  if (!row) return null;
  row.sync_status = SYNC_STATUS.SYNCED;
  await db.put(STORE_EVIDENCE, row);
  return row;
}
