# ANTHRYX AI — Demo Runbook

**SIH26024 · Team DATA_HELIX**

Every expected result below was actually reproduced end-to-end against a
live backend and a live browser across this project's verification
history — nothing here describes planned or aspirational behavior.

## Setup

```bash
python3 scripts/bootstrap_demo.py   # migrations + idempotent demo data
cd backend && uvicorn app.main:app --port 8000 &
cd dashboard/streamlit && ANTHRYX_API_BASE_URL=http://localhost:8000 streamlit run app.py &
```

For password-free local demo startup, set `ANTHRYX_DEMO_AUTO_LOGIN=true`
before starting Streamlit; it authenticates as the demo ADMIN through the
backend API. Otherwise, login with `demo.admin@example.com` /
`DemoAdmin123!` (printed by the bootstrap script; two other demo roles
are also created).

---

## FLOW 1 — Document compliance

**Login** → **M1 Documents** page → select the demo mine → upload any
document image against one of its statutory obligations → **Run OCR
extraction** → mark **Verified**.

**Expected**: OCR engine shown honestly (`TESSERACT` or `demo-fallback`,
never a fabricated live Bhashini result). After verification, the **M0
Compliance** page shows that obligation's status has moved off `MISSING`.

## FLOW 2 — Field inspection through to CAPA closure

**M2 / React PWA** → log in, select the mine, **capture** tab, choose
"Inspection". The form fetches the mine's **real M0 checklist** — not an
empty list — and requires marking compliant/non-compliant on every item
before it will submit.

**Expected**: marking any item non-compliant with HIGH/CRITICAL severity
automatically raises a CAPA (confirmed: `capas_created` in the sync
response is non-empty). Walk that CAPA through **M4 CAPA** →
`ASSIGNED → IN_PROGRESS → EVIDENCE_SUBMITTED → VERIFIED → CLOSED`,
attaching a document at the evidence step and a justification note at
verification/closure. On closure, the **M3 Risk** page for that mine will
show "this score may be stale" — the system never claims risk improved
just because a CAPA closed.

## FLOW 3 — Risk scoring from real application data

**M3 Risk** page → select the mine → **Build / refresh features from
live application data**.

**Expected**: a real feature vector built from that mine's own
inspection/violation history (`violations_last_12m`, etc. — never MSHA
rows, never a synthetic file). `production_hours` and `avg_penalty_amount`
are always `None`/blocked. The page then shows a real risk score, a real
SHAP explanation table, and — if the category is HIGH — a `RISK_ALERT`
CAPA is created automatically (refreshing again does not duplicate it).

## FLOW 4 — Sensor anomaly

**M5 Anomaly** page → select the mine → **Simulate ANOMALOUS
telemetry** → **Run M5 Isolation Forest detection**.

**Expected**: a visible `SIMULATED TELEMETRY` badge throughout, a real
Isolation Forest anomaly score, and — if flagged anomalous — a CAPA with
`source_type=SENSOR_ANOMALY` (never `RISK_ALERT`). The page states
explicitly this is never an accident probability.

## FLOW 5 — Automatic escalation

Create (or wait for) a CAPA past its due date. A real, live APScheduler
background job (`services/escalation_scheduler.py`, started by FastAPI's
own startup event) checks on a short interval — `scheduler_interval_
seconds`, default 30 seconds, a deliberate prototype/demo cadence, not a
production-realistic daily cron — and transitions an overdue CAPA to
`ESCALATED`, writing an audit entry. This is a real state change, not
only a displayed level, and it happens automatically while the
application is simply running: no manual API call is required. The same
job also checks grievance SLA deadlines on the same tick.

**Expected** (verified directly against real data): first check → status
becomes `ESCALATED`; identical re-run same day → no change, no duplicate
audit entry; later re-run → escalation level increases further if the
CAPA is still open and more overdue.

## FLOW 6 — Audit and reporting

**Audit Ledger** page → **Verify ledger**.

**Expected**: "Chain intact — N entries checked," explicitly **not**
described as immutable or a blockchain.

**Reports** page → select the mine → **Generate report** → **Download
PDF**.

**Expected**: a real PDF, headed "REPRESENTATIVE STATUTORY RETURN" with
an explicit "NOT an official DGMS/MSHA statutory form" disclaimer, and
real obligation/CAPA/incident data from that mine's own history.

## FLOW 7 — Grievance filing and SLA escalation

**Grievances** page → **File a grievance** → pick a mine, category,
description → submit.

**Expected**: a real, persisted grievance with a genuine SLA deadline
(`grievance_sla_days`, default 7). If a grievance's deadline has already
passed, the live scheduler (same job as Flow 5) automatically moves it
to `ESCALATED` with a real audit entry — no manual trigger needed. A
resolution requires a note; the transition is rejected without one.

## FLOW 8 — Approval chain

**Approvals** page → request an approval for a CAPA → decide each stage
in order: **Mine Manager → Subsidiary GM → Corporate Office**.

**Expected**: a stage cannot be decided out of order (an earlier
undecided stage blocks it), and a **rejection at any stage ends the
chain there** — it never silently continues to the next stage.
Requesting a second approval for the same CAPA returns the existing
chain rather than creating a duplicate.

## FLOW 9 — Contractor Passport

**Contractor Passport** page → select a contractor.

**Expected**: real engagement history across every mine that contractor
has worked at, with CAPA counts attributed only to the actual contract
date window (not a blanket "every CAPA at this mine, ever" claim). A
debarred contractor still holding an active engagement elsewhere
triggers a real cross-site warning.

---

## What NOT to claim during the demo

- The M3 score is a **risk score**, not "the probability of an
  accident."
- M5 detects an **anomaly**, not "risk."
- A voice transcript is `DEMO_FALLBACK` unless the UI genuinely shows
  `LIVE_BHASHINI` (no live Bhashini credentials are configured in this
  project by default).
- The audit ledger is **tamper-evident**, never "immutable" or
  "blockchain."
- Docker has been statically validated only, never actually built/run in
  this project's own development environment.
- Closing a CAPA does not itself lower a mine's risk score — it flags the
  mine as needing a fresh feature build, honestly, without pretending the
  situation already improved.
