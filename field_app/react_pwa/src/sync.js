/**
 * Retry queue for pending field evidence (M2).
 *
 * Posts each queued record through the real /field-evidence endpoint,
 * authenticated with the signed-in user's token. A record's own
 * client_uuid is what makes a retried POST idempotent server-side; this
 * queue never invents or re-derives that value at flush time.
 */

import { listPending, markSynced, SYNC_STATUS } from './db.js';
import { postFieldEvidence } from './api.js';

export const API_BASE = import.meta.env?.VITE_API_BASE_URL ?? 'http://localhost:8000';

export function isOnline() {
  return typeof navigator === 'undefined' ? true : navigator.onLine;
}

export async function flushQueue({ postImpl = postFieldEvidence } = {}) {
  if (!isOnline()) return { attempted: 0, synced: 0, skipped: 'offline' };

  const pending = await listPending();
  let synced = 0;
  const failures = [];

  for (const row of pending) {
    try {
      const payload = {
        client_uuid: row.client_uuid,
        kind: row.kind,
        mine_id: row.payload.mine_id,
        client_timestamp: row.client_timestamp,
        latitude: row.payload.latitude ?? null,
        longitude: row.payload.longitude ?? null,
        gps_accuracy_m: row.payload.gps_accuracy_m ?? null,
        location_method: row.payload.location_method ?? 'NONE',
        mock_location_reported: row.payload.mock_location_reported ?? null,
        device_fingerprint: row.payload.device_fingerprint ?? null,
        notes: row.payload.notes ?? null,
        photo_hash: row.payload.photo_hash ?? null,
        findings: row.payload.findings ?? [],
        attendance: row.payload.attendance ?? null,
        incident: row.payload.incident ?? null,
      };
      const response = await postImpl(payload);
      if (response.ok) {
        await markSynced(row.client_uuid);
        synced += 1;
      } else {
        failures.push({ client_uuid: row.client_uuid, status: response.status });
      }
    } catch (err) {
      // Leave the record PENDING_SYNC and try again on the next flush -
      // a network failure here is not a reason to drop field evidence.
      failures.push({ client_uuid: row.client_uuid, error: String(err) });
    }
  }

  return { attempted: pending.length, synced, failures, status: SYNC_STATUS.SYNCED };
}

