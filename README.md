# ANTHRYX AI

Governance and compliance platform for coal mines.
Smart India Hackathon 2026, problem statement **SIH26024**. Team **DATA_HELIX**.

> **Build status: functional prototype, all fifteen application pages
> wired to real backend endpoints.** M0-M7 plus Grievances, Approvals,
> Contractor Passport, Alerts, and Settings are implemented end to end
> against real, persisted data. This is a hackathon prototype, not a
> certified or production-verified system — see "Known limitations"
> below before relying on any specific claim.

---

## 1. What ANTHRYX AI does

A coal mine safety-compliance platform that connects statutory
obligations, field evidence, a real machine-learning accident-risk
score, corrective-action tracking, and a tamper-evident audit trail into
one closed loop:

```
statutory obligation -> evidence (document or field) -> M3 risk score
    -> prioritized CAPA action -> verification/closure -> audit record
    -> future risk recalculation
```

The goal is not to replace a mine inspector's judgment. The system
orders an inspection queue and explains why; a human always makes the
final call, and every override is recorded.

## 2. Architecture

```
        React PWA (M2 field evidence only)
                    |
User -> Streamlit dashboard
                    |
                    v
                FastAPI
                    |
               PostgreSQL
```

Both the Streamlit dashboard and the React PWA are HTTP clients of the
same FastAPI backend. Neither imports a SQLAlchemy model or opens a
database session directly — authorization is enforced in exactly one
place (`backend/app/deps.py`), so a client cannot bypass a rule by
hiding a page.

## 3. Modules (M0-M7)

| ID | Module | What it does |
|----|--------|---------------|
| M0 | Statutory Rule Registry | Machine-readable CMR 2017 / Mines Act obligations, versioned, with a `MISSING` status when evidence has never been supplied for an applicable rule. `GET /mines/{id}/checklist` drives the PWA's real inspection checklist directly from these rules — never a hardcoded or empty list |
| M1 | Document Intelligence | Upload -> Tesseract OCR -> confidence-gated Bhashini/demo fallback -> human verification -> rule linkage |
| M2 | Field Evidence | Offline-first React PWA: inspection/attendance/incident capture, IndexedDB queue, idempotent authenticated sync, anti-spoof signals |
| M3 | Risk Intelligence Engine | Real supervised model trained on real MSHA data — see §4 |
| M4 | CAPA & Escalation | Six-state corrective-action lifecycle with an escalation ladder; consumes M3 risk alerts and M5 anomaly alerts as separate source types |
| M5 | Sensor Anomaly Detection | Real Isolation Forest over **simulated** methane/CO/airflow telemetry — see §5 |
| M6 | Statutory Reporting & Audit Ledger | Hash-chained tamper-evident ledger; PDF compliance report generation from real data |
| M7 | Role-Based Dashboards & Risk Map | Fifteen Streamlit pages (see §10), CDN-independent risk map as the primary view |

Beyond the numbered M0-M7 core, the product also includes: **Grievances**
(worker/community complaints with a real SLA and automatic escalation),
**Approvals** (a three-stage sign-off chain over a CAPA), **Contractor
Passport** (cross-site engagement and debarment visibility), **Alerts**
(a real-time aggregation view, no new schema), and **Settings** (profile
and, for ADMIN, a user list). All of these are wired to real, persisted
data — see §10 for the full page list and §M-equivalent sections below
for each one's behaviour.

## 4. The M3 model

Trained exclusively on real MSHA (US Mine Safety and Health
Administration) open government data — never on Indian government data,
never on synthetic data. Strict temporal split: train on windows ending
2000-2018, validate 2019-2021, test 2022-2024 once. Selected
`HistGradientBoostingClassifier` over `RandomForestClassifier` by
validation PR-AUC. Explained with real `shap.TreeExplainer` output, never
fabricated. Measured metrics and the exact feature contract actually
shipped with this package, not a separate report file:

- `artifacts/accident_risk_model_metrics.json` — real, measured
  ROC-AUC/PR-AUC/precision/recall/confusion matrix/calibration deciles
  for the frozen artifact
- `artifacts/accident_risk_model_feature_schema.json` — the exact
  9-column MSHA-training feature order and the 7-column Indian-deployable
  subset
- `GET /risk/model-status` — returns both of the above live, alongside
  the artifact's SHA-256 and training data-contract, so a reviewer never
  has to trust a static file being in sync with the running model

**Vocabulary**: the output is an **M3 risk score** — a ranking and
prioritization signal. It is not asserted as a calibrated accident
probability outside the specific MSHA population it was measured
against, and the dashboard says so explicitly.

**Indian deployment restrictions, enforced in code, not just documented**:
`production_hours` and `avg_penalty_amount` are forced to `NaN`
unconditionally in deployable (Indian) scoring mode — never accepted from
a caller, never imputed, never presented as a real Indian observation.
`ml/m3_service.py`'s `DEPLOYABLE_BLOCKED_FEATURES` set is the single
source of truth for this.

### 4a. Live feature construction (Phase 5 Part 3)

`POST /risk/mines/{mine_id}/build-features` derives the deployable
feature vector for a real mine from this application's own tables — not
from MSHA rows, not from a synthetic file. Every mapping is documented in
one place, `backend/services/feature_builder.py`'s module docstring:

| Feature | Source | Honest limitation |
|---|---|---|
| `violations_last_12m`, `ss_violations_last_12m`, `repeat_violation_ratio` | Non-compliant `InspectionFinding` rows, trailing 365 days | — |
| `days_since_last_inspection` | Most recent `FieldEvidence(kind=INSPECTION)` | `NULL` if never inspected |
| `mine_size_avg_employees` | `Mine.average_employee_count` | `NULL` if not set |
| `mine_type` | `Mine.mine_type` | `MIXED` has no MSHA-side target |
| `inspection_hours_last_12m` | **No source exists** | Always `NULL` — never approximated |
| `production_hours`, `avg_penalty_amount` | **Blocked, unconditionally** | Never read even though `Mine.production_hours_last_year` exists as a column |

Scoring a mine end-to-end as a normal user: `build-features` then
`GET /risk/mines/{id}` — no direct database access required.

**M3 → CAPA**: a HIGH risk score automatically raises a `RISK_ALERT` CAPA,
idempotent (a mine has at most one active `RISK_ALERT` CAPA at a time —
refreshing the risk page never duplicates it).

**CAPA closure → rescore**: closing a CAPA never fabricates an immediate
risk improvement. It sets `Mine.rescore_required = True`, surfaced
honestly in the risk API/UI ("this score may be stale"), and cleared only
when `build-features` actually runs again for that mine.

## 5. M5 Isolation Forest

A genuinely trained, unsupervised `IsolationForest` (`n_estimators=200`,
fixed seed) scoring **simulated** methane/CO/airflow telemetry for
unusual multivariate combinations — a pattern a single-threshold hardware
alarm would miss. Every telemetry reading and every M5 page in the
dashboard is labelled `SIMULATED`; no physical sensor is connected.

**Reproducible demo telemetry**: `POST /sensors/simulate` (or the M5
Anomaly page's two buttons) generates three deterministic-when-seeded
readings via `backend/services/telemetry_simulator.py`, using the same
generator shapes the Isolation Forest was actually trained on. It takes
a `mine_id`, never a geographic coordinate, and every reading is written
with `provenance=SIMULATED`.

**M3 and M5 are kept structurally separate**, not just semantically:
separate model artifacts, separate database tables (`MlPrediction` vs
`AnomalyExplanation`), separate API endpoints, separate CAPA source types
(`RISK_ALERT` vs `SENSOR_ANOMALY`), separate dashboard pages, and neither
ever shares a chart axis or color scale with the other. A dedicated test
(`test_m3_and_m5_write_to_different_tables_never_cross_contaminate`)
verifies this directly rather than relying on convention.

## 6. OCR pipeline

Locked policy, implemented exactly: **Tesseract primary** (local, free)
-> confidence check against a configurable threshold (`ocr_confidence_
threshold`, default 70) -> **Bhashini OCR fallback** via the shared
provider abstraction if confidence is low or a non-Latin script is
suspected -> human verification. Uploads are size-capped and
content-type-allowlisted (`services/uploads.py`); a filename is never
used to construct a filesystem path.

## 7. Bhashini integration

`BhashiniProvider` and `DemoFallbackProvider` implement the same
interface (OCR, ASR, translation). Credentials come from environment
variables only — never hardcoded, verified by a dedicated test. If
credentials are absent, or a live call fails, the system reports
`DEMO_FALLBACK` or `BHASHINI_UNAVAILABLE` honestly; **`LIVE_BHASHINI` is
only ever returned after an actual completed, successful API response**
— confirmed by code audit in Phase 5. This project has never had live
Bhashini credentials configured; every OCR fallback and voice transcript
produced in development and testing has genuinely been `DEMO_FALLBACK`,
and is shown as such everywhere, including the dashboard UI.

## 8. M4 CAPA loop

`OPEN -> ASSIGNED -> IN_PROGRESS -> EVIDENCE_SUBMITTED -> VERIFIED ->
CLOSED`, with automatic escalation on a missed due date. Evidence and
justification are required at the gated transitions; the state machine
(`services/capa.py`) rejects an invalid transition rather than silently
allowing it. Overdue CAPA items feed back into future risk scoring,
closing the loop the project is built around.

**Auto-creation, not just manual entry**: a CAPA is raised automatically
from three real triggers — an M3 HIGH risk score (`RISK_ALERT`), an M5
detected anomaly (`SENSOR_ANOMALY`), and a HIGH/CRITICAL-severity
inspection finding or incident (`VIOLATION`/`INCIDENT`), the last two
sharing one idempotent helper (`services/capa_triggers.py`) so a retried
request never duplicates a CAPA.

**Automatic escalation**: `backend/services/escalation_scheduler.py` runs
the existing, unmodified escalation ladder as a real, **live background
job** — `app/main.py`'s FastAPI startup event starts a genuine
APScheduler `BackgroundScheduler` when `settings.scheduler_enabled` is
true (the default; disabled automatically when `environment=test`, so
the 215-test backend suite runs with zero background-thread
interference). It performs the actual `ESCALATED` state transition
rather than only computing a displayed level, and runs the grievance
SLA check (below) on the same tick. **Interval is `scheduler_interval_
seconds` (default 30 seconds) — a deliberate prototype/demo cadence so
a reviewer can observe automatic escalation within one session, not a
production-realistic daily or hourly cron.** A production deployment
would lengthen this and document the new cadence; the mechanism itself
does not change. Idempotent by design: a CAPA's `escalation_level`
column is the durable high-water mark, so re-running the check any
number of times never re-fires the same escalation twice — verified by
seeding an overdue CAPA, starting the real server, and observing the
very first live tick escalate it with zero manual API calls.

## 9. M6 tamper-evident audit ledger

```
row_hash = SHA256(seq | actor_id | action | entity_type | entity_id |
                   timestamp | payload_json | prev_hash)
```

Append-only; verification recomputes every row's hash and checks
sequence and `prev_hash` continuity. A `tamper-drill` endpoint
demonstrates detection on an **in-memory copy** — nothing is ever written
to the real ledger by the drill, so it can be run repeatedly without
leaving history in a broken state. **Always described as tamper-evident.
Never immutable. Never a blockchain.**

## 10. Streamlit dashboard

Fifteen role-aware pages — Overview, M3 Risk, M5 Anomaly, M4 CAPA, M1
Documents, M0 Compliance, Voice Incident, Audit Ledger, **Risk Map**,
Alerts, Grievances, Approvals, Contractor Passport, Settings, Reports —
all calling FastAPI over HTTP via a shared `ApiClient` — no direct
database access anywhere in `dashboard/`. Light institutional theme:
white/off-white surfaces, a single restrained navy accent, no
gradients, no glassmorphism. Genuinely validated with headless Chromium
(Playwright) against a live backend across multiple hardening passes,
not merely inspected — including real clicks (not just page loads) on
the OCR upload/extract flow, the M5 simulate/detect buttons, CAPA state
transitions, and a live-scheduler escalation observed with zero manual
API calls.

## 11. React PWA (M2 only)

Login, mine selection, inspection/attendance/incident capture with photo
hashing, voice-incident recording (`MediaRecorder`), an offline
IndexedDB queue keyed by client-generated UUID for idempotent sync, and
a submitted-evidence view. Genuinely validated with headless Chromium
including a real authenticated cross-origin sync to a live backend.

## 12. Data provenance

| Category | Examples | Rule |
|---|---|---|
| REAL | MSHA archives, Q181/Q679 (Indian govt), seeded demo mine coordinates | Used as-is; MSHA trains M3, Q181/Q679 validate/calibrate only, never train |
| SIMULATED | M5 telemetry | Always labelled `SIMULATED`, never presented as measured |
| MSHA_REFERENCE_ONLY | `production_hours_msha_reference_only` | Real MSHA value, never an Indian observation |
| BLOCKED | `production_hours`, `avg_penalty_amount` for Indian inference | Forced to `NaN`, never a fabricated number |
| DEMO_FALLBACK | Bhashini output with no live credentials | Never presented as a live result |

## 13. Synthetic-data boundaries

Q181 (Lok Sabha) and Q679 (Rajya Sabha) Indian government accident data
are used **only** for validation and calibration context — reconciled
exactly against official totals, and **never** used to train, tune, or
select the M3 model. A grep-based check (`grep -rln "q679\|q181"
backend/ml/ backend/api/`) confirms no training or scoring code path
references either dataset. A synthetic Indian-context demo layer exists
(Phase 3I) for UI/pipeline demonstration only, with `label_eligible_for_
training = False` hard-set on every record, and is not part of the live
backend's runtime data path.

## 14. Known limitations

- **Docker build/run has never been verified** — no Docker daemon exists
  in the development sandbox this project was built in, and a direct
  PostgreSQL package install also failed on mirror unavailability. Both
  `docker-compose.yml` and `Dockerfile` are authored and statically
  valid (YAML parses, service dependencies are declared) but genuinely
  unbuilt. **Verify on a machine with Docker before relying on it.**
- **PostgreSQL itself has never been connected to this application** —
  all real runtime testing used the documented SQLite development
  fallback. The schema/migrations use no SQLite-specific construct, but
  that portability is unverified against a live PostgreSQL server.
- **The optional geographic basemap overlay** depends on an external CDN
  (`basemaps.cartocdn.com`) that may be unreachable in a
  firewalled/air-gapped deployment (it is blocked in this project's own
  development sandbox, confirmed via `x-deny-reason: host_not_allowed`).
  This is why the **primary** Risk Map view is a native
  `st.scatter_chart` — real coordinates, real risk-based colour and
  size, zero external network dependency — with the tile-based basemap
  demoted to an explicitly optional, clearly-labelled button. The map is
  never blank/dead regardless of network conditions.
- **The statutory report format is not verified against an official
  Form IV layout** — output is explicitly labelled
  `REPRESENTATIVE_STATUTORY_RETURN`.
- **No production security certification or third-party penetration
  test has been performed.** A self-audit found and fixed several
  genuine issues during development (timing-safe login, upload
  size/content-type limits, CORS allowlisting, no hardcoded secrets —
  see `backend/tests/test_phase5_security.py` for the tests that
  encode these findings); this is
  not a substitute for independent assessment.
- **Login rate limiting is in-memory, per-process** — appropriate for
  this single-worker prototype; a multi-worker production deployment
  would need a shared store (e.g. Redis) for the limit to apply globally,
  documented as a known trade-off, not a silent gap.
- **The full CMR 2017/Mines Act statutory corpus is not digitized** — a
  proof-of-concept set of high-frequency obligations is seeded.

## 15. How to run locally

```bash
cp .env.example .env          # fill in JWT_SECRET (see comment in the file)
pip install -r requirements.txt
python3 scripts/bootstrap_demo.py   # migrations + idempotent demo data - safe to re-run
```

**`scikit-learn` is pinned to an exact version (`==1.8.0`), not a lower
bound.** This is deliberate, not an oversight: the frozen M3 model
artifact was pickled under 1.8.0, and a newer release's internal module
layout can change enough that `joblib.load()` fails outright on the same
file — this was found and fixed during a clean-install reliability gate
(a fresh virtualenv installing `scikit-learn>=1.5` pulled 1.9.1 and broke
model loading with `ModuleNotFoundError: No module named '_loss'`). Do
not loosen this pin without re-verifying the model still loads.

`bootstrap_demo.py` creates clearly labelled DEMO/SYNTHETIC records only
(5 demo mines across real coalfield regions — Jharia, Korba, Raniganj,
Talcher, Singrauli — with approximate, explicitly-labelled coordinates;
3 demo users across the ADMIN/MINE_MANAGER/FIELD_INSPECTOR roles; a
proof-of-concept statutory rule set; deliberately varied real inspection
findings and SIMULATED telemetry per mine so the demo shows the full
LOW/MEDIUM/HIGH risk spectrum on first login rather than one flat state;
one seeded grievance, one seeded approval chain, one seeded contractor)
and prints the demo login credentials on completion. It never inserts
MSHA or Q679/Q181 rows as if they were Indian mine-level operational
data, and is safe to run any number of times — every insert is keyed on
a natural unique field and skipped if already present; re-running only
refreshes each mine's M3 feature/score (itself idempotent and harmless,
never fabricating an improvement).

## 16. How to run migrations

```bash
alembic upgrade head
```

Verified in this project's own testing: a full `upgrade head -> downgrade
base -> upgrade head` round-trip succeeds cleanly from an empty database.

## 17. How to start the backend

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/api/v1/health`

## 18. How to start Streamlit

```bash
cd dashboard/streamlit
export ANTHRYX_API_BASE_URL=http://localhost:8000
streamlit run app.py
```

## 19. How to build/run the React PWA

```bash
cd field_app/react_pwa
npm install
npm run dev        # development server
npm run build       # production build; verified to succeed in this project
npm test            # offline-queue/sync unit tests; verified passing
```

## 20. Docker

`docker-compose.yml` (db + api + dashboard services) and `Dockerfile` are
authored and statically valid — but **Docker runtime has not been
verified in this project's development environment**, because no Docker
daemon was available there. Before relying on the Docker path:

```bash
docker compose config     # validate the compose file on your machine
docker compose up --build # build and start for real
```

Nothing about the configuration is known to be wrong; it simply has
never been executed end to end. Say so plainly if asked — do not assume
it works just because it looks correct.

## Testing

```bash
cd backend && pytest              # 235 tests: domain, security, closed-loop integration, end-to-end flows
cd field_app/react_pwa && npm test  # 7 tests: offline queue, idempotent sync
```

No test requires network access, a live Bhashini account, or a running
PostgreSQL server.

## M3 label definition (locked, frozen since Phase 3C.11)

`label_accident_next_12m = 1` if any accident at the mine in the
calendar-year label window carries `DEGREE_INJURY_CD` in
`{01, 02, 03, 04}` (fatality; permanent disability; days away from work;
days away plus restricted activity). A label window whose only candidate
accidents are coded `?` is excluded as indeterminate — never coerced to a
negative. Population, negative definition and window definition are
frozen: `POPULATION_BASIS = A_Q1Q3`, `NEGATIVE_DEFINITION = N1`,
`WINDOW_DEFINITION = CALENDAR_YEAR`. This locked definition, and the
model trained against it, are verifiable directly from the shipped
artifact and endpoint — `GET /risk/model-status` returns the exact
label encoding alongside the frozen model's SHA-256, so the definition
above can be checked against the running system rather than a separate
document.

## Licence and data provenance

MSHA data is US public-domain open government data. Q181/Q679 are Indian
Parliament public-record data. OpenStreetMap tiles are used under the
ODbL. All Python and JavaScript dependencies are open source.

## Further reading

- `artifacts/accident_risk_model_metrics.json` — real, measured M3 model metrics (shipped)
- `artifacts/accident_risk_model_feature_schema.json` — exact M3 feature order (shipped)
- `artifacts/isolation_forest_metrics.json`, `artifacts/isolation_forest_feature_schema.json` — same, for M5 (shipped)
- `GET /risk/model-status` — the above, returned live, alongside the artifact's SHA-256
- `backend/tests/test_phase5_security.py` — the security self-audit findings, encoded as tests
- `ANTHRYX_DEMO_RUNBOOK.md` — a concrete demo sequence (shipped)
