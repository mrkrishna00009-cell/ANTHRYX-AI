/**
 * Thin HTTP client for the FastAPI backend. No SQLAlchemy, no direct DB
 * access - matches the same architecture rule as the Streamlit dashboard.
 */

export const API_BASE = import.meta.env?.VITE_API_BASE_URL ?? 'http://localhost:8000';

export function getToken() {
  return localStorage.getItem('anthryx_token');
}

export function setToken(token) {
  if (token) localStorage.setItem('anthryx_token', token);
  else localStorage.removeItem('anthryx_token');
}

async function request(path, { method = 'GET', json, params, headers = {} } = {}) {
  const token = getToken();
  const url = new URL(`${API_BASE}${path}`);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));

  const opts = {
    method,
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  };
  if (json !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(json);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} from ${path}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

export async function login(email, password) {
  const result = await request('/api/v1/auth/login', { method: 'POST', json: { email, password } });
  setToken(result.access_token);
  return result;
}

export function logout() {
  setToken(null);
}

export function me() {
  return request('/api/v1/auth/me');
}

export function listMines() {
  return request('/api/v1/mines');
}

export function getChecklist(mineId) {
  return request(`/api/v1/mines/${mineId}/checklist`);
}

export function listMyEvidence(mineId) {
  return request('/api/v1/field-evidence', { params: { mine_id: mineId } });
}

/** Raw fetch target for the offline sync queue - kept separate from
 * `request()` because a queued record must be posted exactly as stored,
 * without the app re-deriving anything from current auth state at flush
 * time (the token is still attached, but the payload is the client's own). */
export async function postFieldEvidence(payload) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/field-evidence`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  return res;
}

export async function postVoiceIncident({ clientUuid, mineId, category, severity, sourceLanguage, audioBlob }) {
  const token = getToken();
  const url = new URL(`${API_BASE}/api/v1/field-evidence/voice-incident`);
  url.searchParams.set('client_uuid', clientUuid);
  url.searchParams.set('mine_id', mineId);
  url.searchParams.set('category', category);
  url.searchParams.set('severity', severity);
  url.searchParams.set('source_language', sourceLanguage);

  const form = new FormData();
  form.append('audio', audioBlob, 'incident.webm');

  const res = await fetch(url, {
    method: 'POST',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}
