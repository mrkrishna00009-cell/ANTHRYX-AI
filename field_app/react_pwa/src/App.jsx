import { useEffect, useState, useCallback } from 'react';
import { countPending, queueEvidence, newClientUuid, EVIDENCE_KIND } from './db.js';
import { isOnline, flushQueue } from './sync.js';
import * as api from './api.js';

async function sha256Hex(blob) {
  const buf = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

function Login({ onSignedIn }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    try {
      await api.login(email, password);
      const user = await api.me();
      onSignedIn(user);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <main className="shell">
      <h1>ANTHRYX Field</h1>
      <p className="meta">Offline-first field evidence capture &middot; M2</p>
      <form className="panel" onSubmit={submit}>
        <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button type="submit">Sign in</button>
        {error && <p className="meta error">{error}</p>}
      </form>
    </main>
  );
}

function MineSelect({ mines, mineId, onChange }) {
  return (
    <label className="mine-select">
      Mine
      <select value={mineId ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>Choose a mine</option>
        {mines.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
      </select>
    </label>
  );
}

function CaptureForm({ mineId, onQueued }) {
  const [kind, setKind] = useState(EVIDENCE_KIND.INCIDENT);
  const [notes, setNotes] = useState('');
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('MEDIUM');
  const [photo, setPhoto] = useState(null);
  const [gps, setGps] = useState(null);
  const [gpsError, setGpsError] = useState(null);
  const [status, setStatus] = useState(null);
  const [checklist, setChecklist] = useState(null);
  const [checklistError, setChecklistError] = useState(null);
  const [findingResults, setFindingResults] = useState({});

  useEffect(() => {
    if (kind !== EVIDENCE_KIND.INSPECTION || !mineId) { setChecklist(null); return; }
    setChecklistError(null);
    api.getChecklist(mineId)
      .then((data) => { setChecklist(data.checklist); setFindingResults({}); })
      .catch((err) => setChecklistError(String(err)));
  }, [kind, mineId]);

  function setFinding(ruleId, field, value) {
    setFindingResults((prev) => ({ ...prev, [ruleId]: { ...prev[ruleId], [field]: value } }));
  }

  function captureGps() {
    if (!navigator.geolocation) { setGpsError('Geolocation not available in this browser.'); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => setGps({
        latitude: pos.coords.latitude, longitude: pos.coords.longitude,
        gps_accuracy_m: pos.coords.accuracy, mock_location_reported: pos.mocked ?? null,
      }),
      (err) => setGpsError(err.message),
    );
  }

  async function submit(e) {
    e.preventDefault();
    if (!mineId) { setStatus('Choose a mine first.'); return; }

    let photoHash = null;
    if (photo) photoHash = await sha256Hex(photo);

    let findings = [];
    if (kind === EVIDENCE_KIND.INSPECTION) {
      if (!checklist || !checklist.length) {
        setStatus('No M0 checklist items apply to this mine yet - nothing to submit.');
        return;
      }
      const missing = checklist.filter((item) => findingResults[item.rule_id]?.compliant === undefined);
      if (missing.length) {
        setStatus(`Mark compliant/non-compliant for all ${checklist.length} checklist items before submitting.`);
        return;
      }
      findings = checklist.map((item) => ({
        rule_id: item.rule_id,
        question: item.question,
        compliant: findingResults[item.rule_id].compliant,
        severity: findingResults[item.rule_id].compliant ? null : item.severity,
        observation: findingResults[item.rule_id]?.observation || null,
      }));
    }

    const payload = {
      mine_id: mineId,
      latitude: gps?.latitude ?? null, longitude: gps?.longitude ?? null,
      gps_accuracy_m: gps?.gps_accuracy_m ?? null,
      location_method: gps ? 'GPS_SURFACE' : 'NONE',
      mock_location_reported: gps?.mock_location_reported ?? null,
      device_fingerprint: localStorage.getItem('anthryx_device_fingerprint') ?? null,
      notes: notes || null,
      photo_hash: photoHash,
      findings,
      attendance: null,
      incident: kind === EVIDENCE_KIND.INCIDENT ? { category: category || 'General', severity, source: 'FORM' } : null,
    };
    const row = await queueEvidence({ kind, payload });
    setStatus(`Queued locally as ${row.client_uuid} - will sync when online.`);
    setNotes(''); setPhoto(null); setFindingResults({});
    onQueued();
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Capture evidence</h2>
      <label>Kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value={EVIDENCE_KIND.INSPECTION}>Inspection</option>
          <option value={EVIDENCE_KIND.ATTENDANCE}>Attendance</option>
          <option value={EVIDENCE_KIND.INCIDENT}>Incident</option>
        </select>
      </label>
      {kind === EVIDENCE_KIND.INSPECTION && (
        <div className="checklist">
          <h3>M0 statutory checklist</h3>
          {checklistError && <p className="meta error">{checklistError}</p>}
          {!checklistError && !checklist && <p className="meta">Loading applicable rules...</p>}
          {checklist && checklist.length === 0 && (
            <p className="meta">No M0 rules apply to this mine's type yet.</p>
          )}
          {checklist && checklist.map((item) => (
            <div key={item.rule_id} className="checklist-item">
              <p><strong>{item.statute} {item.clause}</strong> ({item.severity}) - {item.question}</p>
              <div className="checklist-controls">
                <label><input type="radio" name={`compliant-${item.rule_id}`}
                       checked={findingResults[item.rule_id]?.compliant === true}
                       onChange={() => setFinding(item.rule_id, 'compliant', true)} /> Compliant</label>
                <label><input type="radio" name={`compliant-${item.rule_id}`}
                       checked={findingResults[item.rule_id]?.compliant === false}
                       onChange={() => setFinding(item.rule_id, 'compliant', false)} /> Non-compliant</label>
              </div>
              <input placeholder="Observation (optional)"
                     value={findingResults[item.rule_id]?.observation || ''}
                     onChange={(e) => setFinding(item.rule_id, 'observation', e.target.value)} />
            </div>
          ))}
        </div>
      )}
      {kind === EVIDENCE_KIND.INCIDENT && (
        <>
          <label>Category<input value={category} onChange={(e) => setCategory(e.target.value)} /></label>
          <label>Severity
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </>
      )}
      <label>Notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <label>Photo
        <input type="file" accept="image/*" capture="environment"
               onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      {photo && <p className="meta">Photo selected: {photo.name} ({photo.size} bytes) - hash computed on submit.</p>}
      <button type="button" onClick={captureGps}>Capture GPS (surface/pit-mouth only)</button>
      {gps && <p className="meta identifier">lat {gps.latitude.toFixed(5)}, lon {gps.longitude.toFixed(5)}, &plusmn;{Math.round(gps.gps_accuracy_m)}m</p>}
      {gpsError && <p className="meta">{gpsError}. Underground verification uses QR/NFC checkpoints, not GPS.</p>}
      <button type="submit">Queue evidence (works offline)</button>
      {status && <p className="meta">{status}</p>}
    </form>
  );
}

function VoiceIncident({ mineId }) {
  const [recording, setRecording] = useState(false);
  const [mediaRecorder, setMediaRecorder] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('MEDIUM');
  const [language, setLanguage] = useState('hi');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      setChunks([]);
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) setChunks((prev) => [...prev, e.data]);
      };
      recorder.start();
      setMediaRecorder(recorder);
      setRecording(true);
    } catch (err) {
      setError(`Microphone unavailable: ${err}`);
    }
  }

  function stopRecording() {
    mediaRecorder?.stop();
    setRecording(false);
  }

  async function submit() {
    if (!mineId) { setError('Choose a mine first.'); return; }
    if (!chunks.length) { setError('Record audio first.'); return; }
    setResult(null);
    setError(null);
    try {
      const blob = new Blob(chunks, { type: 'audio/webm' });
      const response = await api.postVoiceIncident({
        clientUuid: newClientUuid(), mineId, category: category || 'Voice-reported concern',
        severity, sourceLanguage: language, audioBlob: blob,
      });
      setResult(response);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="panel">
      <h2>Voice incident</h2>
      <p className="meta">audio &rarr; Bhashini ASR &rarr; original transcript &rarr; Bhashini NMT &rarr; English translation &rarr; incident &rarr; CAPA &rarr; audit</p>
      <label>Category<input value={category} onChange={(e) => setCategory(e.target.value)} /></label>
      <label>Severity
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <label>Source language
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          {['hi', 'bn', 'te', 'or', 'en'].map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
      </label>
      {!recording
        ? <button type="button" onClick={startRecording}>Start recording</button>
        : <button type="button" onClick={stopRecording}>Stop recording</button>}
      <button type="button" onClick={submit} disabled={recording || !chunks.length}>Submit voice incident</button>
      {error && <p className="meta error">{error}</p>}
      {result && (
        <div>
          <p className="meta">ASR: {result.asr_provider_status}{result.asr_provider_status !== 'LIVE_BHASHINI' && ' (NOT a live Bhashini result)'}</p>
          <p className="meta">Translation: {result.nmt_provider_status}{result.nmt_provider_status !== 'LIVE_BHASHINI' && ' (NOT a live Bhashini result)'}</p>
          <p>Original transcript: {result.original_transcript || '(none)'}</p>
          <p>English translation: {result.translated_transcript || '(none)'}</p>
          {result.capa_id && <p className="meta">CAPA raised: {result.capa_id}</p>}
        </div>
      )}
    </div>
  );
}

function QueueStatus({ pendingCount, online, onFlush, flushResult }) {
  return (
    <div className="panel">
      <div className="status-line"><span>Connection</span><span className="identifier">{online ? 'online' : 'offline'}</span></div>
      <div className="status-line"><span>Records pending sync</span><span className="identifier">{pendingCount ?? '...'}</span></div>
      <button type="button" onClick={onFlush} disabled={!online}>Sync now</button>
      {flushResult && (
        <p className="meta">
          Attempted {flushResult.attempted}, synced {flushResult.synced}
          {flushResult.skipped && ` (skipped: ${flushResult.skipped})`}
          {flushResult.failures?.length > 0 && ` - ${flushResult.failures.length} still pending`}
        </p>
      )}
    </div>
  );
}

function SubmittedEvidence({ mineId }) {
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!mineId) return;
    api.listMyEvidence(mineId).then(setEvidence).catch((err) => setError(String(err)));
  }, [mineId]);

  if (!mineId) return null;
  return (
    <div className="panel">
      <h2>Submitted evidence</h2>
      {error && <p className="meta error">{error}</p>}
      {evidence?.length ? (
        <table>
          <thead><tr><th>Kind</th><th>Server time</th><th>Location method</th><th>Spoof flags</th></tr></thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.id}>
                <td>{e.kind}</td><td>{e.server_timestamp}</td><td>{e.location_method}</td>
                <td>{(e.spoof_flags || []).join(', ') || 'none'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="meta">No evidence submitted for this mine yet.</p>}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [mines, setMines] = useState([]);
  const [mineId, setMineId] = useState(null);
  const [pending, setPending] = useState(null);
  const [online, setOnline] = useState(isOnline());
  const [flushResult, setFlushResult] = useState(null);
  const [tab, setTab] = useState('capture');

  const refreshPending = useCallback(() => {
    countPending().then(setPending).catch(() => setPending(null));
  }, []);

  useEffect(() => {
    if (!api.getToken()) return;
    api.me().then(setUser).catch(() => api.logout());
  }, []);

  useEffect(() => {
    if (!user) return;
    api.listMines().then(setMines).catch(() => setMines([]));
  }, [user]);

  useEffect(() => {
    refreshPending();
    const update = () => setOnline(isOnline());
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, [refreshPending]);

  if (!user) return <Login onSignedIn={setUser} />;

  async function doFlush() {
    const result = await flushQueue();
    setFlushResult(result);
    refreshPending();
  }

  return (
    <main className="shell">
      <h1>ANTHRYX Field</h1>
      <p className="meta">{user.email} &middot; {user.role}
        <button type="button" onClick={() => { api.logout(); setUser(null); }} className="link-btn">Sign out</button>
      </p>
      <MineSelect mines={mines} mineId={mineId} onChange={setMineId} />
      <QueueStatus pendingCount={pending} online={online} onFlush={doFlush} flushResult={flushResult} />
      <nav className="tabs">
        {['capture', 'voice', 'submitted'].map((t) => (
          <button key={t} type="button" className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {tab === 'capture' && <CaptureForm mineId={mineId} onQueued={refreshPending} />}
      {tab === 'voice' && <VoiceIncident mineId={mineId} />}
      {tab === 'submitted' && <SubmittedEvidence mineId={mineId} />}
    </main>
  );
}
