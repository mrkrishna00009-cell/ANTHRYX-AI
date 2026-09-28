"""ANTHRYX AI dashboard - Phase 4 Part 2.

Every page calls the FastAPI backend over HTTP through ApiClient. No
SQLAlchemy model, no database session, and no direct PostgreSQL
connection exists anywhere in this file. Backend RBAC is authoritative;
this file only hides navigation entries a role's token would be refused
for anyway - it never grants an action the backend would reject.

Role-aware navigation uses the ACTUAL backend Role enum values (ADMIN,
DGMS_REGULATOR, SUBSIDIARY_HEAD, MINE_MANAGER, MINE_SAFETY_OFFICER,
FIELD_INSPECTOR) rather than inventing a parallel naming scheme that
would not correspond to any real permission the backend enforces.
"""

from __future__ import annotations

import streamlit as st

from api_client import ApiClient, ApiError
from theme import FONT_MONO, FONT_UI, get_theme, risk_color
from ui_components import empty_state, error_state, format_timestamp, kpi_row, section_header, severity_badge, timeline_event_row

st.set_page_config(
    page_title="ANTHRYX AI", page_icon=None, layout="wide",
    initial_sidebar_state="expanded",
)

# --- theme selection ---------------------------------------------------
# Persisted via the URL query string, which survives a browser refresh -
# the real client-side persistence mechanism available to a Streamlit
# app without adding a new dependency. st.session_state alone would only
# survive reruns within the same tab, not a refresh.
_THEME_MODE = st.query_params.get("theme", "light")
if _THEME_MODE not in ("light", "dark"):
    _THEME_MODE = "light"
_T = get_theme(_THEME_MODE)

st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    """,
    unsafe_allow_html=True,
)
# NOTE: the Google Fonts link above cannot load in this project's own
# development sandbox (its network egress proxy returns 403
# host_not_allowed for fonts.googleapis.com, confirmed by direct test) -
# it degrades to the system-font stack below, which is why FONT_UI is
# ordered to look genuinely good on its own, not merely as a silent
# fallback from a font that never arrives. In an unrestricted
# deployment the Google Fonts link loads normally and IBM Plex Sans/Mono
# render as intended.
st.markdown(
    f"""
    <style>
      html, body, [class*="css"] {{ font-family: {FONT_UI}; }}
      code, .anthryx-id {{ font-family: {FONT_MONO}; }}
      .stApp {{ background-color: {_T['SURFACE']}; color: {_T['TEXT']}; }}
      section[data-testid="stSidebar"] {{ background-color: {_T['SURFACE_SUNKEN']}; }}
      .anthryx-panel {{
        border: 1px solid {_T['BORDER']}; border-radius: 3px;
        background: {_T['SURFACE_SUNKEN']}; padding: 14px 16px;
      }}
      .anthryx-meta {{ color: {_T['TEXT_MUTED']}; font-size: 0.86rem; }}
      .m5-badge {{
        display: inline-block; padding: 2px 8px; border-radius: 3px;
        background: {_T['SURFACE_SUNKEN']}; color: {_T['TEXT_MUTED']}; font-size: 0.78rem; font-weight: 600;
        border: 1px solid {_T['BORDER']};
      }}
      h1, h2, h3, p, span, label, div {{ color: {_T['TEXT']}; }}
      .anthryx-meta, .anthryx-meta * {{ color: {_T['TEXT_MUTED']} !important; }}
      a {{ color: {_T['ACCENT']}; }}
      [data-testid="stMetricValue"] {{ color: {_T['TEXT']}; }}
      [data-testid="stVegaLiteChart"] svg {{ background-color: {_T['SURFACE']} !important; }}
      [data-testid="stDataFrame"] {{ background-color: {_T['SURFACE']}; }}
      button[kind], .stButton button, .stFormSubmitButton button {{
        color: {_T['TEXT']} !important; border-color: {_T['BORDER']} !important;
        background-color: {_T['SURFACE_SUNKEN']} !important;
      }}
      button[kind]:hover, .stButton button:hover, .stFormSubmitButton button:hover {{
        color: {_T['ACCENT']} !important; border-color: {_T['ACCENT']} !important;
      }}
      .block-container {{ max-width: 1200px; padding-top: 2rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

ROLE_PAGES = {
    "ADMIN": ["Overview", "M3 Risk", "M5 Anomaly", "M4 CAPA", "M1 Documents",
             "M0 Compliance", "Voice Incident", "Audit Ledger", "Risk Map", "Alerts",
             "Grievances", "Approvals", "Contractor Passport", "Compliance Copilot", "Settings", "Reports"],
    "DGMS_REGULATOR": ["Overview", "M3 Risk", "M5 Anomaly", "M4 CAPA", "M1 Documents",
                       "M0 Compliance", "Audit Ledger", "Risk Map", "Alerts",
                       "Grievances", "Approvals", "Contractor Passport", "Compliance Copilot", "Settings", "Reports"],
    "SUBSIDIARY_HEAD": ["Overview", "M3 Risk", "M5 Anomaly", "M4 CAPA", "M0 Compliance", "Risk Map", "Alerts",
                       "Grievances", "Approvals", "Contractor Passport", "Compliance Copilot", "Settings", "Reports"],
    "MINE_MANAGER": ["Overview", "M3 Risk", "M5 Anomaly", "M4 CAPA", "M1 Documents",
                     "M0 Compliance", "Voice Incident", "Risk Map", "Alerts",
                     "Grievances", "Approvals", "Contractor Passport", "Settings"],
    "MINE_SAFETY_OFFICER": ["Overview", "M4 CAPA", "M1 Documents", "M0 Compliance", "Voice Incident",
                           "Grievances", "Settings"],
    "FIELD_INSPECTOR": ["Overview", "Voice Incident", "M4 CAPA", "Grievances", "Settings"],
}


def _client() -> ApiClient:
    if "client" not in st.session_state:
        st.session_state.client = ApiClient()
    return st.session_state.client


def render_login():
    st.markdown("<div style='height:8vh;'></div>", unsafe_allow_html=True)
    left, center, right = st.columns([1, 1.3, 1])
    with center:
        st.markdown(
            f"""
            <div style="text-align:center;margin-bottom:22px;">
              <div style="font-size:2.1rem;font-weight:700;color:{_T['TEXT']};letter-spacing:-0.01em;">ANTHRYX AI</div>
              <div style="color:{_T['TEXT_MUTED']};font-size:0.92rem;margin-top:4px;">
                Coal mine compliance and governance &middot; SIH26024 &middot; Team DATA_HELIX
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        client = _client()
        with st.container(border=True):
            with st.form("login"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            try:
                client.login(email, password)
                me = client.me()
                st.session_state.user = me
                st.rerun()
            except ApiError as exc:
                error_state(f"Sign-in failed: {exc}", _T)


def render_overview(client: ApiClient, user: dict):
    st.title("Overview")
    st.caption("Where is the risk, why, what's pending, who owns it, has it been resolved.")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines are visible to this role yet. An ADMIN can create one under Risk Map / mine setup.", _T)
        return

    try:
        overview = client.get("/api/v1/mines/risk-overview")
    except ApiError as exc:
        error_state(f"Could not load risk overview: {exc}", _T)
        return

    high_risk = sum(1 for m in overview if m["risk_category"] == "HIGH")
    open_capa = sum(m["open_capa_count"] for m in overview)
    overdue_capa = sum(m["overdue_capa_count"] for m in overview)
    anomalous = sum(1 for m in overview if m.get("m5_is_anomaly"))
    stale = sum(1 for m in overview if m.get("rescore_required"))

    closed_capa = 0
    recent_incidents = 0
    for m in mines:
        try:
            capas = client.get("/api/v1/capa", mine_id=m["id"])
            closed_capa += sum(1 for c in capas if c["status"] in ("CLOSED", "VERIFIED"))
        except ApiError:
            pass
        try:
            evidence = client.get("/api/v1/field-evidence", mine_id=m["id"], kind="INCIDENT")
            recent_incidents += len(evidence)
        except ApiError:
            pass

    try:
        grievances = client.get("/api/v1/grievances")
        breached_grievances = sum(1 for g in grievances if g["sla_breached"])
    except ApiError:
        grievances, breached_grievances = [], 0
    try:
        approvals = client.get("/api/v1/approvals")
        pending_approvals = sum(1 for a in approvals if a["final_decision"] == "PENDING")
    except ApiError:
        approvals, pending_approvals = [], 0
    try:
        contractors = client.get("/api/v1/contractors")
        debarred_contractors = sum(1 for c in contractors if c["status"] == "DEBARRED")
    except ApiError:
        contractors, debarred_contractors = [], 0

    section_header("Risk", None, _T)
    kpi_row([
        {"label": "Mines in scope", "value": len(mines), "tone": "neutral"},
        {"label": "High-risk mines", "value": high_risk, "tone": "bad" if high_risk else "good"},
        {"label": "M5 anomalies active", "value": anomalous, "tone": "warn" if anomalous else "good",
         "hint": "SIMULATED telemetry - never an accident-risk figure"},
        {"label": "Scores needing rebuild", "value": stale, "tone": "warn" if stale else "good",
         "hint": "CAPA closed since last scored"},
    ], _T)

    section_header("Compliance", None, _T)
    kpi_row([
        {"label": "Open CAPA items", "value": open_capa, "tone": "warn" if open_capa else "good"},
        {"label": "Overdue CAPA", "value": overdue_capa, "tone": "bad" if overdue_capa else "good"},
        {"label": "Closed/verified CAPA", "value": closed_capa, "tone": "good"},
        {"label": "Recent incidents", "value": recent_incidents, "tone": "neutral"},
    ], _T)

    section_header("Actions & Governance", None, _T)
    kpi_row([
        {"label": "Pending approvals", "value": pending_approvals, "tone": "warn" if pending_approvals else "good"},
        {"label": "Grievances (SLA breached)", "value": breached_grievances, "tone": "bad" if breached_grievances else "good"},
        {"label": "Total grievances", "value": len(grievances), "tone": "neutral"},
        {"label": "Debarred contractors (active)", "value": debarred_contractors, "tone": "bad" if debarred_contractors else "good"},
    ], _T)

    st.divider()
    st.subheader("Mine risk comparison")
    st.caption("M3 operational risk score per mine - real data from /api/v1/mines/risk-overview.")
    scored = [m for m in overview if m["risk_score"] is not None]
    if scored:
        import pandas as pd
        chart_df = pd.DataFrame({
            "Mine": [m["name"] for m in scored],
            "M3 risk score": [m["risk_score"] for m in scored],
        })
        # A genuine Streamlit structural limit, found and reverted rather
        # than shipped wrong: st.bar_chart's `color` list colors an entire
        # Y-series, not individual bars, and passing a categorical column
        # name instead hands colour assignment to Vega-Lite's own default
        # category scale - which is not guaranteed to align with this
        # app's severity semantics (a real test run assigned red to
        # MEDIUM and blue to HIGH, actively misleading rather than
        # helping). Real risk category per mine is still shown, correctly
        # colour-coded via severity_badge, in the table directly below.
        # Raw Altair, not st.bar_chart: st.bar_chart follows Streamlit's
        # own static build-time theme config, not this app's dynamic CSS
        # toggle, so it silently keeps a white background in dark mode -
        # a real defect only found by actually looking at a screenshot.
        # Altair's own .configure() call is themed explicitly instead.
        import altair as alt
        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("Mine:N", title="Mine", sort=None),
                y=alt.Y("M3 risk score:Q", title="M3 risk score (0-1)"),
                color=alt.value(_T["ACCENT"]),
                tooltip=["Mine", "M3 risk score"],
            )
            .properties(height=280)
            .configure(background=_T["SURFACE"])
            .configure_view(strokeWidth=0)
            .configure_axis(
                labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                gridColor=_T["BORDER"], domainColor=_T["BORDER"],
            )
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        empty_state("No mine has been scored yet - build features on the M3 Risk page.", _T)

    st.subheader("Mines requiring attention")
    sorted_overview = sorted(overview, key=lambda m: m["risk_score"] or -1, reverse=True)
    for m in sorted_overview:
        badge = severity_badge(m["risk_category"], _T)
        st.markdown(
            f'{badge} &nbsp; **{m["name"]}** ({m["code"]}) &middot; '
            f'score {m["risk_score"] if m["risk_score"] is not None else "not yet scored"} '
            f'&middot; {m["open_capa_count"]} open CAPA, {m["overdue_capa_count"]} overdue',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<span class="anthryx-meta">M5 sensor-anomaly information is shown separately on the '
        '"M5 Anomaly" page and is never an accident-risk figure.</span>',
        unsafe_allow_html=True,
    )
    try:
        audit = client.get("/api/v1/audit", limit=5)
        st.subheader("Recent audit activity")
        st.dataframe(
            [{"seq": a["seq"], "action": a["action"], "entity": a["entity_type"],
              "timestamp": format_timestamp(a["timestamp"])} for a in audit],
            use_container_width=True, hide_index=True,
        )
    except ApiError:
        st.caption("Audit activity unavailable for this role.")


def render_risk(client: ApiClient):
    st.title("M3 Risk Intelligence")
    st.caption(
        "Supervised accident-risk score. A ranking/prioritisation signal - "
        "not asserted as a calibrated probability outside the model's MSHA test population."
    )
    try:
        status = client.get("/api/v1/risk/model-status")
    except ApiError as exc:
        error_state(f"Could not reach the model status endpoint: {exc}", _T)
        return

    model = status["model"]
    st.markdown(
        f'<div class="anthryx-panel">Model status: <b>{model["status"]}</b> &middot; '
        f'version/hash: <span class="anthryx-id">{(model.get("sha256") or "-")[:16]}...</span></div>',
        unsafe_allow_html=True,
    )
    if model["status"] != "TRAINED":
        st.warning(model["detail"])
        return

    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return

    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names))
    mine_id = mine_names[chosen]

    if st.button("Build / refresh features from live application data"):
        try:
            built = client.post(f"/api/v1/risk/mines/{mine_id}/build-features")
        except ApiError as exc:
            error_state(f"Feature build failed: {exc}", _T)
        else:
            st.success(
                f"Features built for window ending {built['window_end_date']}. "
                f"violations_last_12m={built['violations_last_12m']}, "
                f"days_since_last_inspection={built['days_since_last_inspection']}. "
                f"production_hours and avg_penalty_amount remain BLOCKED (None)."
            )
            if built.get("rescore_was_required"):
                empty_state("This mine had a pending rescore flag from a closed CAPA - now resolved by this rebuild.", _T)
            for note in built.get("availability_notes", []):
                st.caption(f"&middot; {note}", unsafe_allow_html=True)

    try:
        result = client.get(f"/api/v1/risk/mines/{mine_id}")
    except ApiError as exc:
        empty_state(f"No score available for this mine yet: {exc}", _T)
        return

    if result.get("implemented") is False:
        st.info(result.get("detail", "No MlFeature row exists for this mine yet."))
        return

    if result.get("rescore_required"):
        st.warning(
            "A CAPA for this mine closed since this score was computed. "
            + result.get("rescore_note", "")
        )

    cat = result["risk_category"]
    st.markdown(
        f'<h2 style="color:{risk_color(cat, _THEME_MODE)}">{result["risk_score"]} &middot; {cat}</h2>',
        unsafe_allow_html=True,
    )
    _model_version_display = result['model_version'].rsplit('/', 1)[-1]  # never leak the server filesystem path
    st.caption(f"Model version: {_model_version_display} - artifact hash: {result['artifact_hash'][:16]}...")
    st.caption(result["vocabulary_note"])
    if result.get("capa_created"):
        st.success(f"A new RISK_ALERT CAPA was created: {result['capa_id']}")
    elif result.get("capa_id"):
        st.caption(f"An active RISK_ALERT CAPA already covers this mine: {result['capa_id']}")

    st.subheader("Contributing factors")
    explanation = result.get("explanation")
    if explanation is None:
        empty_state("No SHAP explanation is available for this prediction.", _T)
    else:
        st.caption(f"Method: {result.get('explanation_method', '-')} (per-instance, this mine only - not global importance)")
        rows = sorted(explanation.items(), key=lambda kv: abs(kv[1]), reverse=True)
        st.bar_chart({f: v for f, v in rows}, x_label="Feature", y_label="SHAP contribution to this score", height=280, color=_T["ACCENT"])
        st.dataframe(
            [{"Feature": f, "SHAP contribution": v} for f, v in rows],
            use_container_width=True, hide_index=True,
        )

    st.subheader("Risk trend")
    try:
        history = client.get(f"/api/v1/risk/mines/{mine_id}/history")
    except ApiError as exc:
        history = []
    if len(history) >= 2:
        st.line_chart(
            {h["scored_at"][:19]: h["risk_score"] for h in history},
            x_label="Scored at", y_label="M3 risk score (0-1)",
        )
    elif len(history) == 1:
        st.info(f"Only one real score recorded so far ({history[0]['scored_at'][:19]}) - "
               "a trend needs at least two. Rebuild features again later to add a second point.")
    else:
        empty_state("No scoring history yet for this mine.", _T)

    st.markdown(
        '<span class="anthryx-meta">production_hours and avg_penalty_amount are BLOCKED for '
        'Indian inference and are never displayed as zero - they are forced to NaN and excluded '
        'from this score, not silently defaulted.</span>',
        unsafe_allow_html=True,
    )


def render_anomaly(client: ApiClient):
    st.title("M5 Operational Anomaly")
    st.markdown('<span class="m5-badge">SIMULATED TELEMETRY</span>', unsafe_allow_html=True)
    st.caption(
        "Unsupervised outlier score over simulated methane/CO/airflow readings. "
        "This is NEVER an accident probability and is never M3 risk."
    )
    try:
        status = client.get("/api/v1/sensors/status")
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not reach the backend: {exc}", _T)
        return
    st.info(status["notice"])

    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="anomaly_mine")
    mine_id = mine_names[chosen]

    sim_col1, sim_col2 = st.columns(2)
    with sim_col1:
        if st.button("Simulate NORMAL telemetry"):
            try:
                client.post("/api/v1/sensors/simulate", params={"mine_id": mine_id, "mode": "normal"})
                st.success("Three SIMULATED normal-range readings recorded.")
            except ApiError as exc:
                error_state(f"Simulation failed: {exc}", _T)
    with sim_col2:
        if st.button("Simulate ANOMALOUS telemetry"):
            try:
                client.post("/api/v1/sensors/simulate", params={"mine_id": mine_id, "mode": "anomaly"})
                st.success("Three SIMULATED anomalous-combination readings recorded.")
            except ApiError as exc:
                error_state(f"Simulation failed: {exc}", _T)
    st.caption(
        "Demo-only generator, not a physical sensor feed - see services/telemetry_simulator.py. "
        "Uses the same generator shapes the Isolation Forest was trained to recognise."
    )

    try:
        readings = client.get("/api/v1/sensors/readings", mine_id=mine_id, limit=20)
    except ApiError as exc:
        error_state(f"Could not load readings: {exc}", _T)
        return
    if readings:
        st.subheader("SIMULATED telemetry over time")
        st.caption(
            "Real simulated readings from services/telemetry_simulator.py, charted as recorded. "
            "This axis and colour are never shared with the M3 risk score chart on the M3 Risk page."
        )
        from collections import defaultdict
        by_sensor = defaultdict(dict)
        for r in readings:
            by_sensor[r["sensor_kind"]][r["recorded_at"][:19]] = r["value"]
        for sensor_kind, series in by_sensor.items():
            st.caption(sensor_kind)
            if len(series) >= 2:
                st.line_chart(series, x_label="Recorded at", y_label="Reading value (SIMULATED)")
            else:
                empty_state(
                    f"Only {len(series)} {sensor_kind.lower()} reading recorded so far - "
                    "a trend chart needs at least two. Simulate telemetry above to add more.",
                    _T,
                )
        st.dataframe(
            [{"Sensor": r["sensor_kind"], "Value": r["value"], "Recorded": r["recorded_at"],
              "Provenance": r["provenance"]} for r in readings],
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No readings recorded for this mine yet.")

    if st.button("Run M5 Isolation Forest detection"):
        try:
            result = client.post("/api/v1/sensors/detect", params={"mine_id": mine_id})
        except ApiError as exc:
            st.warning(f"Detection unavailable: {exc}")
        else:
            if result.get("implemented") is False:
                st.info(result["detail"])
            else:
                st.metric("M5 anomaly score (decision function)", result["anomaly_score"])
                st.write("Anomalous combination:", result["is_anomaly"])
                st.caption(result["separation_note"])
                if result.get("capa_id"):
                    st.success(f"CAPA raised: {result['capa_id']}")

    st.subheader("M5 anomaly score history")
    st.caption(
        "Real recorded anomaly scores over time for this mine - separate endpoint, separate "
        "vocabulary (anomaly_score/is_anomaly), separate axis from the M3 risk trend chart. "
        "Never plotted alongside or scaled against the M3 risk score."
    )
    try:
        anomaly_hist = client.get(f"/api/v1/sensors/mines/{mine_id}/anomaly-history")
    except ApiError:
        anomaly_hist = []
    if len(anomaly_hist) >= 2:
        st.line_chart(
            {h["scored_at"][:19]: h["anomaly_score"] for h in anomaly_hist},
            x_label="Scored at", y_label="M5 anomaly score (Isolation Forest decision function)",
        )
    elif len(anomaly_hist) == 1:
        empty_state("Only one anomaly score recorded so far for this mine - a trend needs at least two.", _T)
    else:
        empty_state("No anomaly detection has been run yet for this mine.", _T)


def render_capa(client: ApiClient, user: dict):
    st.title("M4 CAPA & Escalation")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="capa_mine")
    mine_id = mine_names[chosen]

    try:
        items = client.get("/api/v1/capa", mine_id=mine_id)
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not items:
        empty_state("No CAPA items for this mine.", _T)
        return

    from collections import Counter
    section_header("CAPA status distribution", "Real counts of this mine's CAPA items by current status - not a fabricated or demo chart.", _T)
    status_counts = Counter(i["status"] for i in items)
    st.bar_chart(dict(status_counts), x_label="Status", y_label="Count", height=220, color=_T["ACCENT"])
    closed_count = status_counts.get("CLOSED", 0)
    st.caption(f"{closed_count} of {len(items)} CAPA item(s) for this mine are CLOSED.")

    section_header("CAPA items", None, _T)
    for item in items:
        badge = severity_badge(item["severity"], _T)
        status_badge = severity_badge(item["status"], _T)
        with st.expander(f"{item['source_type']} — {item['severity']} — {item['status']}"):
            st.markdown(f"{badge} {status_badge}", unsafe_allow_html=True)
            st.write({
                "CAPA ID": item["id"], "Mine": mine_id, "Source": item["source_type"],
                "Status": item["status"], "Severity": item["severity"],
                "Due date": item.get("due_date"), "Escalation level": item.get("escalation_level"),
                "Description": item.get("description"),
            })
            new_status = st.selectbox(
                "Transition to", ["ASSIGNED", "IN_PROGRESS", "EVIDENCE_SUBMITTED", "VERIFIED", "CLOSED"],
                key=f"transition_{item['id']}",
            )
            note = st.text_input("Justification (required for some transitions)", key=f"note_{item['id']}")
            if st.button("Apply transition", key=f"btn_{item['id']}"):
                try:
                    client.post(f"/api/v1/capa/{item['id']}/transition",
                               {"to_status": new_status, "note": note or None})
                    st.success("Transition applied.")
                    st.rerun()
                except ApiError as exc:
                    error_state(f"Transition rejected by the backend: {exc}", _T)


def render_documents(client: ApiClient):
    st.title("M1 Documents")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="doc_mine")
    mine_id = mine_names[chosen]

    with st.expander("Upload a new document"):
        doc_type = st.text_input("Document type", value="Safety Certificate")
        if st.button("Create document record"):
            try:
                doc = client.post("/api/v1/documents", {"mine_id": mine_id, "doc_type": doc_type})
                st.success(f"Document created: {doc['id']}")
                st.session_state["last_doc_id"] = doc["id"]
            except ApiError as exc:
                error_state(f"Could not create document: {exc}", _T)

    with st.expander("Run OCR extraction"):
        doc_id = st.text_input("Document ID", value=st.session_state.get("last_doc_id", ""))
        uploaded = st.file_uploader("Upload an image to OCR", type=["png", "jpg", "jpeg"])
        if st.button("Extract") and doc_id and uploaded:
            try:
                result = client.post_file(
                    f"/api/v1/documents/{doc_id}/extract",
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                )
                st.write(f"Engine used: **{result['engine']}** - status: {result['provider_status']}")
                if result["engine"] not in ("TESSERACT",):
                    st.caption("This result did NOT come from Tesseract locally succeeding - see detail below.")
                st.caption(result["detail"])
                st.text_area("Extracted text", result["extracted_text"], height=100)
            except ApiError as exc:
                error_state(f"OCR extraction failed: {exc}", _T)

    try:
        docs = client.get("/api/v1/documents", mine_id=mine_id)
    except ApiError as exc:
        error_state(f"Could not load documents: {exc}", _T)
        return
    if docs:
        st.dataframe(
            [{"Doc type": d["doc_type"], "OCR engine": d.get("ocr_engine"),
              "OCR confidence": d.get("ocr_confidence"),
              "Verification": d["verification_status"]} for d in docs],
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No documents for this mine yet.")


def render_compliance(client: ApiClient):
    st.title("M0 Statutory Compliance")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="compliance_mine")
    mine_id = mine_names[chosen]

    try:
        obligations = client.get(f"/api/v1/mines/{mine_id}/obligations")
    except ApiError as exc:
        error_state(f"Could not load obligations: {exc}", _T)
        return
    if not obligations:
        empty_state("No obligations recorded for this mine.", _T)
        return

    from collections import Counter
    status_counts = Counter(o["status"] for o in obligations)
    st.subheader("Obligation status distribution")
    st.caption("Real counts from this mine's obligations - not a time trend (no historical status log exists).")
    st.bar_chart(dict(status_counts), x_label="Status", y_label="Count", height=220, color=_T["ACCENT"])

    st.dataframe(
        [{"Status": o["status"], "Next due": o.get("next_due_date"),
          "Last satisfied": o.get("last_satisfied_date")} for o in obligations],
        use_container_width=True, hide_index=True,
    )
    if any(o["status"] == "MISSING" for o in obligations):
        st.warning(
            "One or more obligations show status MISSING: the rule applies and no "
            "evidence has ever been supplied for it."
        )


def render_voice(client: ApiClient):
    st.title("Voice Incident Reporting")
    st.caption("audio -> Bhashini ASR -> original transcript -> Bhashini NMT -> English translation -> incident -> CAPA -> audit")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="voice_mine")
    mine_id = mine_names[chosen]

    category = st.text_input("Category", value="Ventilation concern")
    severity = st.selectbox("Severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    language = st.selectbox("Source language", ["hi", "bn", "te", "or", "en"])
    audio = st.file_uploader("Upload audio", type=["wav", "mp3", "m4a", "ogg"])

    if st.button("Submit voice incident") and audio:
        import uuid as _uuid
        try:
            result = client.post_file(
                "/api/v1/field-evidence/voice-incident",
                params={
                    "client_uuid": str(_uuid.uuid4()), "mine_id": mine_id,
                    "category": category, "severity": severity, "source_language": language,
                },
                files={"audio": (audio.name, audio.getvalue(), audio.type)},
            )
        except ApiError as exc:
            error_state(f"Voice incident submission failed: {exc}", _T)
            return

        asr_status = result["asr_provider_status"]
        nmt_status = result["nmt_provider_status"]
        if asr_status == "LIVE_BHASHINI":
            st.success("ASR: LIVE Bhashini result")
        else:
            st.warning(f"ASR: {asr_status} - this is NOT a live Bhashini result")
        if nmt_status == "LIVE_BHASHINI":
            st.success("Translation: LIVE Bhashini result")
        else:
            st.warning(f"Translation: {nmt_status} - this is NOT a live Bhashini result")

        st.text_area("Original transcript", result.get("original_transcript") or "(none)")
        st.text_area("English translation", result.get("translated_transcript") or "(none)")
        if result.get("capa_id"):
            empty_state(f"CAPA raised: {result['capa_id']}", _T)


def render_audit(client: ApiClient):
    st.title("Audit Ledger")
    st.caption("Tamper-evident hash chain. Not immutable. Not a blockchain.")
    try:
        entries = client.get("/api/v1/audit", limit=100)
    except ApiError as exc:
        error_state(f"Could not load audit entries: {exc}", _T)
        return
    st.dataframe(
        [{"seq": e["seq"], "timestamp": format_timestamp(e["timestamp"]),
          "actor": (e.get("actor_id") or "system")[:8], "action": e["action"],
          "entity": e["entity_type"], "entity_id": (e.get("entity_id") or "-")[:8],
          "hash": (e.get("row_hash") or "")[:12]} for e in entries],
        use_container_width=True, hide_index=True,
    )
    if st.button("Verify ledger"):
        try:
            result = client.get("/api/v1/audit/verify")
        except ApiError as exc:
            error_state(f"Verification failed: {exc}", _T)
            return
        if result["intact"]:
            st.success(f"Chain intact - {result['entries_checked']} entries checked.")
        else:
            error_state(f"TAMPERING DETECTED at sequence {result['broken_at_seq']}.", _T)


def render_gis(client: ApiClient):
    st.title("Mine Risk Map")
    section_header(
        "Operational risk view",
        "Marker colour reflects M3 operational risk only. M5 sensor-anomaly "
        "state is shown separately in the details panel and never changes marker colour.",
        _T,
    )
    try:
        overview = client.get("/api/v1/mines/risk-overview")
    except ApiError as exc:
        error_state(f"Could not load mine risk overview: {exc}", _T)
        return

    located = [m for m in overview if m.get("latitude") is not None and m.get("longitude") is not None]
    unlocated = [m for m in overview if m not in located]

    RISK_COLOR = {"HIGH": _T["RISK"]["HIGH"], "MEDIUM": _T["RISK"]["MEDIUM"],
                 "LOW": _T["RISK"]["LOW"], None: _T["TEXT_MUTED"]}

    if not located:
        empty_state("No mine in this dataset has coordinates recorded. Nothing is plotted rather than inventing a location.", _T)
    else:
        with st.container(border=True):
            import pandas as pd
            df = pd.DataFrame([
                {"Mine": m["name"], "State": m.get("state") or "-",
                 "Longitude": m["longitude"], "Latitude": m["latitude"],
                 "Risk category": m["risk_category"] or "Not yet scored",
                 "Risk score": m["risk_score"] if m["risk_score"] is not None else 0.05,
                 "color": RISK_COLOR.get(m["risk_category"], "#7f8c8d")}
                for m in located
            ])
            # Primary, tile-free plot: always renders, never depends on an
            # external basemap CDN. Position is lat/long (a real geographic
            # scatter, not a decorative chart) with real risk-based colour and
            # marker size, labelled explicitly as approximate/coalfield-level.
            # Altair (bundled with Streamlit, no external network needed) is
            # used instead of st.scatter_chart specifically because it supports
            # an explicit axis domain - st.scatter_chart always includes 0 in
            # its auto-scaled range, which for real India coalfield coordinates
            # (~82-87 deg E, ~20-24 deg N) shrinks the actual data to a tiny
            # cluster in one corner of an otherwise empty chart.
            import altair as alt
            lon_pad = max((df["Longitude"].max() - df["Longitude"].min()) * 0.15, 0.3)
            lat_pad = max((df["Latitude"].max() - df["Latitude"].min()) * 0.15, 0.3)
            chart = (
                alt.Chart(df)
                .mark_circle(opacity=0.85)
                .encode(
                    x=alt.X("Longitude:Q", scale=alt.Scale(
                        domain=[df["Longitude"].min() - lon_pad, df["Longitude"].max() + lon_pad]),
                        title="Longitude"),
                    y=alt.Y("Latitude:Q", scale=alt.Scale(
                        domain=[df["Latitude"].min() - lat_pad, df["Latitude"].max() + lat_pad]),
                        title="Latitude"),
                    color=alt.Color("color:N", scale=None, legend=None),
                    size=alt.Size("Risk score:Q", scale=alt.Scale(range=[220, 900]), legend=None),
                    tooltip=["Mine", "State", "Risk category", "Risk score"],
                )
                .properties(height=340)
                .configure(background=_T["SURFACE"])
                .configure_view(strokeWidth=0)
                .configure_axis(
                    labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                    gridColor=_T["BORDER"], domainColor=_T["BORDER"],
                )
            )
            st.altair_chart(chart, use_container_width=True)
            st.caption(
                "Plotted by real recorded coordinates (approximate coalfield locations, not surveyed "
                "boundaries) - this view never depends on an external map-tile service, so it always "
                "renders even where a basemap CDN is unreachable."
            )
            legend_cols = st.columns(4)
            for col, (label, color) in zip(legend_cols, [("HIGH", RISK_COLOR["HIGH"]), ("MEDIUM", RISK_COLOR["MEDIUM"]),
                                                          ("LOW", RISK_COLOR["LOW"]), ("No score yet", RISK_COLOR[None])]):
                col.markdown(f'<span style="color:{color}">&#9679;</span> {label}', unsafe_allow_html=True)

            if st.button("Load geographic basemap (requires external network access - optional)"):
                st.caption(
                    "This overlay depends on an external tile provider and may not render in a "
                    "network-restricted environment. The scatter plot above is the reliable, "
                    "always-available view and shows the same real data."
                )
                st.map([{"lat": m["latitude"], "lon": m["longitude"]} for m in located])

    if unlocated:
        st.caption(f"{len(unlocated)} mine(s) have no coordinates and are not shown on the map: "
                  + ", ".join(m["name"] for m in unlocated))

    st.subheader("Mine details")
    if not overview:
        empty_state("No mines available.", _T)
        return
    names = {m["name"]: m for m in overview}
    chosen = st.selectbox("Select a mine to view details", list(names))
    m = names[chosen]

    cols = st.columns(4)
    cols[0].metric("M3 risk score", m["risk_score"] if m["risk_score"] is not None else "not yet scored")
    cols[1].metric("Risk category", m["risk_category"] or "-")
    cols[2].metric("Open CAPA", m["open_capa_count"])
    cols[3].metric("Overdue CAPA", m["overdue_capa_count"])

    if m["rescore_required"]:
        st.warning("A CAPA closed since this score was computed - it may be stale. Rebuild features on the M3 Risk page.")

    st.caption(f"Last inspection: {format_timestamp(m['last_inspection_at']) if m['last_inspection_at'] else 'never inspected'}")
    st.caption(
        f"M5 latest reading: {'ANOMALOUS' if m['m5_is_anomaly'] else 'normal/none run yet' if m['m5_is_anomaly'] is not None else 'no telemetry scored yet'}"
        + (f" (score {m['m5_anomaly_score']})" if m["m5_anomaly_score"] is not None else "")
        + " - SIMULATED, and never the same score as M3 risk."
    )

    if m["explanation"]:
        st.caption("Major contributing factors (real SHAP, this mine only):")
        rows = sorted(m["explanation"].items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
        st.dataframe([{"Feature": f, "Contribution": v} for f, v in rows], use_container_width=True, hide_index=True)
    else:
        st.caption("No risk explanation available yet - build features and score this mine on the M3 Risk page.")

    st.markdown(
        f'<span class="anthryx-meta">Coordinate provenance: {m["coordinate_provenance"]}'
        f'{" (approximate)" if m["coordinate_is_approximate"] else " (surveyed)"}</span>',
        unsafe_allow_html=True,
    )

    with st.expander("Mine risk timeline (real persisted events)"):
        try:
            tl = client.get(f"/api/v1/mines/{m['mine_id']}/timeline", limit=50)
        except ApiError as exc:
            error_state(str(exc), _T)
        else:
            st.caption(tl["note"])
            if tl["event_count"] == 0:
                empty_state("No events recorded yet for this mine.", _T)
            else:
                for e in tl["events"][:20]:
                    timeline_event_row(e, _T)
                if tl["event_count"] > 20:
                    st.caption(f"Showing the 20 most recent of {tl['event_count']} events.")

    with st.expander("Contradiction & drift check (document vs. field record)"):
        try:
            cd = client.get(f"/api/v1/mines/{m['mine_id']}/contradictions")
        except ApiError as exc:
            error_state(str(exc), _T)
        else:
            st.caption(cd["detector_coverage"])
            if cd["contradiction_count"] == 0:
                empty_state("No contradiction detected for this mine's currently-checked rules.", _T, icon="✓")
            else:
                for c in cd["contradictions"]:
                    badge = severity_badge(c["severity"], _T)
                    st.markdown(
                        f'<div style="border-left:3px solid {_T["RISK"]["HIGH"]};padding:6px 0 6px 12px;margin-bottom:6px;">'
                        f'<strong>{c["rule_code"]}</strong> {badge} '
                        f'<span style="color:{_T["TEXT_MUTED"]};font-size:0.8rem;">({c["contradiction_type"].replace("_"," ").title()})</span>'
                        f'<div style="color:{_T["TEXT_MUTED"]};font-size:0.88rem;margin-top:2px;">{c["explanation"]}</div></div>',
                        unsafe_allow_html=True,
                    )


def render_alerts(client: ApiClient):
    st.title("Alerts")
    st.caption(
        "A real-time aggregation of the same data shown elsewhere - HIGH risk mines, "
        "overdue CAPA items, M5 anomalies, and stale (rescore-required) risk scores. "
        "Not a separate stored entity; nothing here is fabricated for this page."
    )
    try:
        overview = client.get("/api/v1/mines/risk-overview")
    except ApiError as exc:
        error_state(f"Could not load alerts: {exc}", _T)
        return

    high_risk = [m for m in overview if m["risk_category"] == "HIGH"]
    overdue = [m for m in overview if m["overdue_capa_count"] > 0]
    anomalous = [m for m in overview if m["m5_is_anomaly"]]
    stale = [m for m in overview if m["rescore_required"]]

    kpi_row([
        {"label": "HIGH risk mines", "value": len(high_risk), "tone": "bad" if high_risk else "good"},
        {"label": "Mines with overdue CAPA", "value": len(overdue), "tone": "bad" if overdue else "good"},
        {"label": "M5 anomalies detected", "value": len(anomalous), "tone": "warn" if anomalous else "good"},
        {"label": "Stale risk scores", "value": len(stale), "tone": "warn" if stale else "good"},
    ], _T)

    if high_risk:
        st.subheader("HIGH risk mines")
        for m in high_risk:
            st.markdown(
                f'{severity_badge("HIGH", _T)} **{m["name"]}** &middot; risk score {m["risk_score"]} '
                f'&middot; {m["open_capa_count"]} open CAPA',
                unsafe_allow_html=True,
            )
    if overdue:
        st.subheader("Mines with overdue CAPA items")
        st.dataframe(
            [{"Mine": m["name"], "Overdue count": m["overdue_capa_count"]} for m in overdue],
            use_container_width=True, hide_index=True,
        )
    if anomalous:
        st.subheader("M5 sensor anomalies (SIMULATED telemetry)")
        st.dataframe(
            [{"Mine": m["name"], "Anomaly score": m["m5_anomaly_score"]} for m in anomalous],
            use_container_width=True, hide_index=True,
        )
    if stale:
        st.subheader("Risk scores needing a rebuild (CAPA closed since last scored)")
        st.dataframe([{"Mine": m["name"]} for m in stale], use_container_width=True, hide_index=True)

    if not (high_risk or overdue or anomalous or stale):
        st.success("No active alerts across any mine visible to this role.")


def render_grievances(client: ApiClient, user: dict):
    st.title("Grievances")
    st.caption(
        "Worker/community grievances - a real SLA deadline is set on filing. "
        "Filing anonymously never stores the filer's identity."
    )

    with st.expander("File a grievance", expanded=False):
        try:
            mines = client.get("/api/v1/mines")
        except ApiError as exc:
            error_state(f"Could not load mines: {exc}", _T)
            mines = []
        if mines:
            mine_names = {m["name"]: m["id"] for m in mines}
            g_mine = st.selectbox("Mine", list(mine_names), key="grievance_mine")
            g_category = st.selectbox(
                "Category", ["SAFETY_CONCERN", "WAGE_DISPUTE", "LAND_ENVIRONMENTAL", "HARASSMENT", "OTHER"],
            )
            g_desc = st.text_area("Describe the concern, location and shift")
            g_anon = st.checkbox("File anonymously")
            if st.button("Submit grievance"):
                if not g_desc.strip():
                    st.warning("Description is required.")
                else:
                    try:
                        client.post("/api/v1/grievances", {
                            "mine_id": mine_names[g_mine], "category": g_category,
                            "description": g_desc, "is_anonymous": g_anon,
                        })
                        st.success("Grievance filed and persisted.")
                        st.rerun()
                    except ApiError as exc:
                        error_state(f"Filing failed: {exc}", _T)

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.selectbox("Status filter", ["All", "OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED"])
    with col2:
        if st.button("Run SLA check now"):
            try:
                result = client.post("/api/v1/grievances/run-sla-check", {})
                n = len(result["escalated"])
                st.info(f"SLA check complete - {n} grievance(s) escalated." if n else
                       "SLA check complete - nothing newly breached.")
            except ApiError as exc:
                error_state(f"SLA check failed: {exc}", _T)

    try:
        params = {} if status_filter == "All" else {"status": status_filter}
        grievances = client.get("/api/v1/grievances", **params)
    except ApiError as exc:
        error_state(str(exc), _T)
        return

    if not grievances:
        empty_state("No grievances match this filter.", _T)
        return

    section_header("Grievance tracking", None, _T)
    for g in grievances:
        status_badge = severity_badge("ESCALATED" if g["sla_breached"] else g["status"], _T)
        with st.expander(f"{g['category']} — {g['status']} {'(anonymous)' if g['is_anonymous'] else ''}"):
            st.markdown(status_badge, unsafe_allow_html=True)
            st.write(g["description"])
            st.caption(f"SLA due: {g['sla_due_at']} - "
                      f"{'BREACHED, ' + str(g['days_overdue']) + ' day(s) overdue' if g['sla_breached'] else 'within SLA'}"
                      f" - escalation level {g['escalation_level']}")
            if g["resolution_note"]:
                st.caption(f"Resolution: {g['resolution_note']}")
            cols = st.columns(3)
            if g["status"] == "OPEN" and cols[0].button("Mark in progress", key=f"prog-{g['id']}"):
                try:
                    client.post(f"/api/v1/grievances/{g['id']}/transition", {"to_status": "IN_PROGRESS"})
                    st.rerun()
                except ApiError as exc:
                    error_state(str(exc), _T)
            if g["status"] in ("OPEN", "IN_PROGRESS", "ESCALATED"):
                note = cols[1].text_input("Resolution note", key=f"note-{g['id']}")
                if cols[2].button("Resolve", key=f"resolve-{g['id']}"):
                    if not note:
                        st.warning("A resolution note is required.")
                    else:
                        try:
                            client.post(f"/api/v1/grievances/{g['id']}/transition",
                                       {"to_status": "RESOLVED", "note": note})
                            st.rerun()
                        except ApiError as exc:
                            error_state(str(exc), _T)


def render_approvals(client: ApiClient):
    st.title("Approvals")
    st.caption("Three-stage sign-off: Mine Manager &rarr; Subsidiary GM &rarr; Corporate Office. "
              "A rejection at any stage ends the chain there.", unsafe_allow_html=True)

    with st.expander("Request approval for a CAPA", expanded=False):
        try:
            mines = client.get("/api/v1/mines")
        except ApiError as exc:
            error_state(f"Could not load mines: {exc}", _T)
            mines = []
        if mines:
            mine_names = {m["name"]: m["id"] for m in mines}
            a_mine = st.selectbox("Mine", list(mine_names), key="approval_mine")
            try:
                capas = client.get("/api/v1/capa", mine_id=mine_names[a_mine])
            except ApiError:
                capas = []
            open_capas = {f"{c['description'][:50]} ({c['status']})": c["id"] for c in capas if c["status"] != "CLOSED"}
            if open_capas:
                a_capa = st.selectbox("CAPA", list(open_capas))
                a_reason = st.text_input("Reason this needs approval")
                if st.button("Request approval"):
                    try:
                        client.post("/api/v1/approvals", {"capa_id": open_capas[a_capa], "reason": a_reason or "-"})
                        st.success("Approval chain created.")
                        st.rerun()
                    except ApiError as exc:
                        error_state(str(exc), _T)
            else:
                st.caption("No open CAPA items for this mine.")

    try:
        chains = client.get("/api/v1/approvals")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not chains:
        empty_state("No approval chains yet.", _T)
        return

    section_header("Approval chains", None, _T)
    for c in chains:
        decision_badge = severity_badge(c["final_decision"], _T)
        with st.expander(f"{c['reason']} "
                         + (f" (awaiting {c['current_stage']})" if c["current_stage"] else "")):
            st.markdown(decision_badge, unsafe_allow_html=True)
            for step in c["steps"]:
                stage_badge = severity_badge(step["decision"], _T)
                waiting = f" - waiting {step['waiting_hours']}h" if step["waiting_hours"] is not None else ""
                st.markdown(f"**{step['stage']}** {stage_badge}{waiting}", unsafe_allow_html=True)
                if step["note"]:
                    st.caption(step["note"])
            if c["current_stage"] and c["final_decision"] == "PENDING":
                note = st.text_input("Decision note", key=f"decnote-{c['chain_id']}")
                d1, d2 = st.columns(2)
                if d1.button("Approve this stage", key=f"appr-{c['chain_id']}"):
                    try:
                        client.post(f"/api/v1/approvals/{c['chain_id']}/decide", {"decision": "APPROVED", "note": note})
                        st.rerun()
                    except ApiError as exc:
                        error_state(str(exc), _T)
                if d2.button("Reject", key=f"rej-{c['chain_id']}"):
                    try:
                        client.post(f"/api/v1/approvals/{c['chain_id']}/decide", {"decision": "REJECTED", "note": note})
                        st.rerun()
                    except ApiError as exc:
                        error_state(str(exc), _T)


def render_contractors(client: ApiClient):
    st.title("Contractor Passport")
    try:
        contractors = client.get("/api/v1/contractors")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not contractors:
        empty_state("No contractors registered yet.", _T)
        return

    names = {f"{c['name']} ({c['code']}) - {c['status']}": c["contractor_id"] for c in contractors}
    chosen = st.selectbox("Contractor", list(names))
    try:
        detail = client.get(f"/api/v1/contractors/{names[chosen]}")
    except ApiError as exc:
        error_state(str(exc), _T)
        return

    if detail.get("cross_site_warning"):
        st.markdown(
            f'<div style="border:1px solid {_T["RISK"]["CRITICAL"]};border-left:4px solid {_T["RISK"]["CRITICAL"]};'
            f'border-radius:4px;padding:12px 14px;background:{_T["SURFACE_SUNKEN"]};color:{_T["TEXT"]};margin-bottom:10px;">'
            f'&#9888; {detail["cross_site_warning"]}</div>',
            unsafe_allow_html=True,
        )

    kpi_row([
        {"label": "Status", "value": detail["status"], "tone": "bad" if detail["status"] == "DEBARRED" else "good"},
        {"label": "Sites engaged", "value": len(detail["sites"]), "tone": "neutral"},
        {"label": "Documents on file", "value": detail["document_count"], "tone": "neutral"},
    ], _T)

    section_header("Site engagements", None, _T)
    st.dataframe(
        [{"Mine": s["mine_name"], "Active": s["is_active"], "Start": s["contract_start"], "End": s["contract_end"],
          "CAPA during engagement": s["capa_count_during_engagement"],
          "Open CAPA": s["open_capa_count_during_engagement"]} for s in detail["sites"]],
        use_container_width=True, hide_index=True,
    )
    st.caption(detail["note"])


def render_settings(client: ApiClient, user: dict):
    st.title("Settings")
    st.subheader("Your profile")
    st.markdown(
        f'<div class="anthryx-panel">Email: <b>{user["email"]}</b><br>'
        f'Role: <b>{user["role"]}</b><br>'
        f'Mine association: <span class="anthryx-id">{user.get("mine_id") or "none (org-wide role)"}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Navigation above is hidden per role for convenience only - the backend enforces every "
        "permission independently and would refuse an action even if a page were reachable."
    )
    if user["role"] == "ADMIN":
        st.subheader("Users (ADMIN only)")
        try:
            users = client.get("/api/v1/auth/users")
            st.dataframe(
                [{"Email": u["email"], "Name": u["full_name"], "Role": u["role"]} for u in users],
                use_container_width=True, hide_index=True,
            )
        except ApiError as exc:
            error_state(f"Could not load users: {exc}", _T)


def render_copilot(client: ApiClient):
    st.title("Compliance Copilot")
    st.caption(
        "Deterministic keyword retrieval over the real, seeded M0 statutory-rule corpus. "
        "No language model is configured anywhere in this project - every fact below is "
        "copied from a real database row, never generated text."
    )
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    mine_names = {"(no mine context)": None} | {m["name"]: m["id"] for m in mines}
    chosen_mine = st.selectbox("Mine context (optional)", list(mine_names))
    question = st.text_input("Ask a compliance question", placeholder="e.g. ventilation standards")

    if st.button("Ask") and question:
        params = {"question": question}
        if mine_names[chosen_mine]:
            params["mine_id"] = mine_names[chosen_mine]
        try:
            result = client.get("/api/v1/compliance-copilot", **params)
        except ApiError as exc:
            error_state(f"Copilot request failed: {exc}", _T)
        else:
            st.caption(f"Mode: {result['provider_mode']} - status: {result['status']}")
            if result["status"] == "GROUNDED_ANSWER":
                st.success(result["answer"])
                st.dataframe(result["matched_rules"], use_container_width=True, hide_index=True)
            else:
                st.info(result["detail"])


def render_reports(client: ApiClient):
    st.title("M6 Statutory Reports")
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    chosen = st.selectbox("Mine", list(mine_names), key="report_mine")
    mine_id = mine_names[chosen]

    if st.button("Generate report"):
        try:
            result = client.post("/api/v1/reports/generate", params={"mine_id": mine_id})
        except ApiError as exc:
            error_state(f"Report generation failed: {exc}", _T)
            return
        st.warning("REPRESENTATIVE STATUTORY RETURN - not an official DGMS/MSHA form.")
        import base64
        pdf_bytes = base64.b64decode(result["pdf_base64"])
        st.download_button("Download PDF", data=pdf_bytes, file_name="anthryx_report.pdf", mime="application/pdf")
        st.json(result["summary"])


PAGES = {
    "Overview": render_overview, "M3 Risk": render_risk, "M5 Anomaly": render_anomaly,
    "M4 CAPA": render_capa, "M1 Documents": render_documents, "M0 Compliance": render_compliance,
    "Voice Incident": render_voice, "Audit Ledger": render_audit, "Risk Map": render_gis,
    "Alerts": render_alerts, "Grievances": render_grievances, "Approvals": render_approvals,
    "Contractor Passport": render_contractors, "Settings": render_settings, "Reports": render_reports,
    "Compliance Copilot": render_copilot,
}


def _theme_toggle():
    label = "Switch to dark theme" if _THEME_MODE == "light" else "Switch to light theme"
    if st.button(label, key=f"theme_toggle_{_THEME_MODE}"):
        st.query_params["theme"] = "dark" if _THEME_MODE == "light" else "light"
        st.rerun()


def main() -> None:
    client = _client()
    if "user" not in st.session_state:
        _theme_toggle()
        render_login()
        return

    user = st.session_state.user
    role = user["role"]
    available = ROLE_PAGES.get(role, ["Overview"])

    with st.sidebar:
        st.markdown("### ANTHRYX AI")
        st.markdown(
            f'<span class="anthryx-meta">{user["email"]} - {role}</span>',
            unsafe_allow_html=True,
        )
        _theme_toggle()
        st.divider()
        page = st.radio("Navigate", available)
        st.divider()
        if st.button("Sign out"):
            del st.session_state["user"]
            st.session_state.client = ApiClient()
            st.rerun()

    fn = PAGES[page]
    if page in ("Overview", "M4 CAPA", "Settings", "Grievances"):
        fn(client, user)
    else:
        fn(client)


if __name__ == "__main__":
    main()
