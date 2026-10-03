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

from html import escape

import streamlit as st

from api_client import ApiClient, ApiError
from theme import FONT_MONO, FONT_UI, get_theme, risk_color
from ui_components import empty_state, error_state, format_timestamp, kpi_row, overview_kpi_grid, section_header, severity_badge, timeline_event_row

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
            .block-container {{ max-width: 1440px; padding-top: 1.25rem; padding-bottom: 2rem; }}
            .overview-heading {{ border-bottom: 1px solid {_T['BORDER']}; padding: 2px 0 15px; margin-bottom: 14px; }}
            .overview-brand {{ color: {_T['ACCENT']} !important; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }}
            .overview-identity {{ color: {_T['TEXT_MUTED']} !important; font-size: 0.82rem; margin-top: 2px; }}
            .overview-heading h1 {{ font-size: 1.8rem; line-height: 1.2; margin: 10px 0 3px; }}
            .overview-heading p {{ color: {_T['TEXT_MUTED']} !important; margin: 0; font-size: 0.94rem; }}
            .overview-user {{ text-align: right; padding-top: 22px; }}
            .overview-user strong {{ display: block; font-size: 0.84rem; overflow-wrap: anywhere; }}
            .overview-user span {{ color: {_T['TEXT_MUTED']} !important; font-size: 0.76rem; }}
            .overview-section {{ margin: 18px 0 8px; }}
            .overview-section h2 {{ font-size: 1rem; line-height: 1.3; margin: 0; }}
            .overview-section p {{ color: {_T['TEXT_MUTED']} !important; font-size: 0.82rem; margin: 2px 0 0; }}
            .overview-kpi-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:8px 0 14px; }}
            .overview-kpi {{ min-width:0; border:1px solid {_T['BORDER']}; border-top:3px solid var(--kpi-tone); border-radius:5px; background:{_T['SURFACE']}; padding:10px 12px 9px; box-shadow:0 1px 2px #1424340a; transition:border-color .15s ease, transform .15s ease; }}
            .overview-kpi:hover {{ border-color:var(--kpi-tone); transform:translateY(-1px); }}
            .overview-kpi-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:8px; }}
            .overview-kpi-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.69rem; font-weight:700; line-height:1.3; letter-spacing:0.04em; }}
            .overview-kpi-status {{ display:inline-flex; align-items:center; gap:4px; color:var(--kpi-tone) !important; font-size:0.64rem; font-weight:700; line-height:1.2; text-align:right; }}
            .overview-kpi-status i {{ width:6px; height:6px; flex:0 0 6px; border-radius:50%; background:var(--kpi-tone); }}
            .overview-kpi-value {{ display:block; color:{_T['TEXT']} !important; font-size:1.55rem; line-height:1.2; margin-top:4px; }}
            .overview-kpi-support {{ color:{_T['TEXT_MUTED']} !important; font-size:0.73rem; line-height:1.3; margin:3px 0 0; }}
            .overview-status-strip {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; border:1px solid {_T['BORDER']}; border-radius:5px; background:{_T['SURFACE_SUNKEN']}; padding:9px 12px; margin:4px 0 18px; }}
            .overview-status-item {{ display:flex; align-items:center; gap:7px; min-width:0; }}
            .overview-status-dot {{ width:7px; height:7px; flex:0 0 7px; border-radius:50%; }}
            .overview-status-copy {{ min-width:0; }}
            .overview-status-copy strong {{ display:block; font-size:0.73rem; line-height:1.3; }}
            .overview-status-copy span {{ display:block; color:{_T['TEXT_MUTED']} !important; font-size:0.68rem; overflow-wrap:anywhere; }}
            .overview-panel {{ border:1px solid {_T['BORDER']}; border-radius:5px; background:{_T['SURFACE']}; padding:10px 12px; }}
            .overview-mine-list {{ display:grid; gap:7px; }}
            .overview-mine-row {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(180px,240px); align-items:center; gap:16px; border:1px solid {_T['BORDER']}; border-radius:4px; background:{_T['SURFACE']}; padding:10px 12px; }}
            .overview-mine-title {{ display:flex; align-items:center; flex-wrap:wrap; gap:7px; min-width:0; }}
            .overview-mine-title strong {{ font-size:0.86rem; overflow-wrap:anywhere; }}
            .overview-mine-code {{ color:{_T['TEXT_MUTED']} !important; font-family:{FONT_MONO}; font-size:0.72rem; }}
            .overview-mine-meta {{ color:{_T['TEXT_MUTED']} !important; font-size:0.75rem; margin-top:3px; }}
            .overview-risk-meter {{ height:5px; background:{_T['SURFACE_SUNKEN']}; border-radius:5px; overflow:hidden; margin-top:5px; }}
            .overview-risk-fill {{ height:100%; border-radius:5px; }}
            .overview-audit-wrap {{ overflow-x:auto; border:1px solid {_T['BORDER']}; border-radius:5px; }}
            .overview-audit-table {{ width:100%; border-collapse:collapse; font-size:0.78rem; }}
            .overview-audit-table th {{ background:{_T['SURFACE_SUNKEN']}; color:{_T['TEXT_MUTED']} !important; font-size:0.67rem; text-align:left; text-transform:uppercase; letter-spacing:0.04em; padding:8px 10px; }}
            .overview-audit-table td {{ border-top:1px solid {_T['BORDER']}; padding:7px 10px; vertical-align:middle; }}
            .overview-audit-action {{ display:inline-block; border:1px solid {_T['BORDER']}; border-radius:4px; background:{_T['SURFACE_SUNKEN']}; padding:2px 6px; font-family:{FONT_MONO}; font-size:0.69rem; white-space:nowrap; }}
            .overview-audit-seq {{ color:{_T['TEXT_MUTED']} !important; font-family:{FONT_MONO}; }}
            section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{ margin-bottom:0; }}
            section[data-testid="stSidebar"] .overview-sidebar-brand strong {{ display:block; color:{_T['ACCENT']} !important; font-size:1.08rem; }}
            section[data-testid="stSidebar"] .overview-sidebar-brand span {{ display:block; color:{_T['TEXT_MUTED']} !important; font-size:0.74rem; line-height:1.3; margin:2px 0 9px; }}
            section[data-testid="stSidebar"] .overview-sidebar-subtitle {{ color:{_T['TEXT_MUTED']} !important; font-size:0.76rem; margin:0 0 10px; }}
            section[data-testid="stSidebar"] .overview-nav-group {{ color:{_T['TEXT_MUTED']} !important; font-size:0.65rem; font-weight:700; letter-spacing:0.08em; margin:13px 0 3px; }}
            section[data-testid="stSidebar"] div.stButton > button {{ min-height:2rem; justify-content:flex-start; padding:0.35rem 0.6rem; border-radius:4px; font-size:0.82rem; }}
            @media (max-width: 1000px) {{ .overview-kpi-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .overview-status-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
            @media (max-width: 640px) {{ .overview-kpi-grid, .overview-status-strip {{ grid-template-columns:1fr; }} .overview-mine-row {{ grid-template-columns:1fr; gap:8px; }} .overview-user {{ text-align:left; padding-top:0; }} }}
                .m3-eyebrow {{ color:{_T['ACCENT']} !important; font-size:0.72rem; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; }}
                .m3-header {{ border-bottom:1px solid {_T['BORDER']}; padding:3px 0 15px; margin-bottom:16px; }}
                .m3-header h1 {{ font-size:1.85rem; line-height:1.2; margin:5px 0; }}
                .m3-header p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.94rem; margin:0; max-width:820px; }}
                .m3-status-card, .m3-assessment-card, .m3-score-card, .m3-context-card, .m3-explanation-card {{ border:1px solid {_T['BORDER']}; border-radius:6px; background:{_T['SURFACE']}; box-shadow:0 2px 6px #1424340a; }}
                .m3-status-card {{ padding:12px 14px; height:100%; }}
                .m3-status-label, .m3-score-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.68rem; font-weight:700; letter-spacing:0.07em; text-transform:uppercase; }}
                .m3-status-value {{ font-size:0.96rem; font-weight:700; margin:4px 0; }}
                .m3-status-meta {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.72rem; line-height:1.45; overflow-wrap:anywhere; }}
                .m3-assessment-intro {{ margin-bottom:8px; }}
                .m3-assessment-intro h2 {{ font-size:1rem; line-height:1.3; margin:0 0 3px; }}
                .m3-assessment-intro p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.8rem; margin:0; }}
                .m3-score-card {{ border-left:5px solid var(--m3-risk); padding:18px 20px; margin:10px 0 12px; }}
                .m3-score-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }}
                .m3-score-value {{ color:var(--m3-risk) !important; font-size:clamp(2rem, 3vw, 2.8rem); font-weight:700; line-height:1.1; margin-top:5px; }}
                .m3-category {{ display:inline-block; border:1px solid var(--m3-risk); border-radius:12px; color:var(--m3-risk) !important; font-size:0.75rem; font-weight:700; padding:4px 10px; }}
                .m3-score-note {{ color:{_T['TEXT_MUTED']} !important; font-size:0.8rem; margin-top:9px; }}
                .m3-scale-head {{ color:{_T['TEXT_MUTED']} !important; display:flex; justify-content:space-between; font-size:0.68rem; margin-top:12px; }}
                .m3-scale-track {{ height:6px; background:{_T['SURFACE_SUNKEN']}; border:1px solid {_T['BORDER']}; border-radius:8px; overflow:hidden; margin-top:4px; }}
                .m3-scale-fill {{ height:100%; background:var(--m3-risk); border-radius:8px; }}
                .m3-context-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; margin:10px 0 16px; }}
                .m3-context-card {{ padding:10px 12px; transition:transform .15s ease, box-shadow .15s ease; }}
                .m3-context-card:hover {{ transform:translateY(-1px); box-shadow:0 4px 10px #14243414; }}
                .m3-context-label {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.67rem; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; }}
                .m3-context-value {{ display:block; font-size:0.82rem; font-weight:600; line-height:1.35; margin-top:4px; overflow-wrap:anywhere; }}
                .m3-callout {{ border-left:3px solid {_T['ACCENT']}; background:{_T['SURFACE_SUNKEN']}; border-radius:4px; padding:11px 14px; margin:12px 0 18px; }}
                .m3-callout strong {{ display:block; font-size:0.8rem; margin-bottom:3px; }}
                .m3-callout span {{ color:{_T['TEXT_MUTED']} !important; font-size:0.78rem; line-height:1.45; }}
                .m3-section {{ margin:20px 0 8px; }}
                .m3-section h2 {{ font-size:1.12rem; line-height:1.3; margin:0; }}
                .m3-section p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.8rem; margin:3px 0 0; }}
                .m3-chart-panel {{ border:1px solid {_T['BORDER']}; border-radius:6px; background:{_T['SURFACE']}; padding:10px 12px; }}
                .m3-feature-table-wrap {{ overflow-x:auto; border:1px solid {_T['BORDER']}; border-radius:5px; margin-top:8px; }}
                .m3-feature-table {{ border-collapse:collapse; width:100%; font-size:0.78rem; }}
                .m3-feature-table th {{ background:{_T['SURFACE_SUNKEN']}; color:{_T['TEXT_MUTED']} !important; font-size:0.67rem; letter-spacing:0.04em; text-align:left; text-transform:uppercase; padding:8px 11px; }}
                .m3-feature-table td {{ border-top:1px solid {_T['BORDER']}; padding:7px 11px; }}
                .m3-feature-table tr:hover td {{ background:{_T['SURFACE_SUNKEN']}; }}
                .m3-feature-name {{ font-family:{FONT_MONO}; font-size:0.74rem; }}
                .m3-feature-value {{ font-family:{FONT_MONO}; font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }}
                .m3-positive {{ color:{_T['RISK']['HIGH']} !important; font-weight:600; }}
                .m3-negative {{ color:{_T['RISK']['LOW']} !important; font-weight:600; }}
                .m3-zero {{ color:{_T['TEXT_MUTED']} !important; }}
                @media (max-width: 900px) {{ .m3-context-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
                @media (max-width: 600px) {{ .m3-context-grid {{ grid-template-columns:1fr; }} .m3-header h1 {{ font-size:1.5rem; }} .m3-score-card {{ padding:14px; }} }}
                .m5-page-header {{ border-bottom:1px solid {_T['BORDER']}; padding:3px 0 14px; margin-bottom:12px; }}
                .m5-page-eyebrow {{ color:{_T['ACCENT']} !important; font-size:0.7rem; font-weight:700; letter-spacing:0.09em; text-transform:uppercase; }}
                .m5-page-header h1 {{ font-size:1.8rem; line-height:1.2; margin:5px 0; }}
                .m5-page-header p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.9rem; margin:0; }}
                .m5-notice {{ display:flex; align-items:flex-start; gap:11px; border:1px solid {_T['BORDER']}; border-left:4px solid {_T['ACCENT']}; border-radius:5px; background:{_T['SURFACE_SUNKEN']}; padding:10px 13px; margin:12px 0; }}
                .m5-notice-copy strong {{ display:block; font-size:0.8rem; margin-bottom:2px; }}
                .m5-notice-copy span {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.76rem; line-height:1.4; }}
                .m5-section {{ margin:17px 0 8px; }}
                .m5-section h2 {{ font-size:1.05rem; line-height:1.3; margin:0; }}
                .m5-section p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.77rem; margin:3px 0 0; }}
                .m5-control-heading h2 {{ font-size:0.98rem; margin:0 0 3px; }}
                .m5-control-heading p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.76rem; margin:0 0 8px; }}
                .m5-snapshot-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:8px 0 4px; }}
                .m5-sensor-card {{ min-width:0; border:1px solid {_T['BORDER']}; border-top:3px solid var(--m5-sensor); border-radius:5px; background:{_T['SURFACE']}; padding:11px 13px; box-shadow:0 2px 5px #1424340a; transition:transform .15s ease, box-shadow .15s ease; }}
                .m5-sensor-card:hover {{ transform:translateY(-1px); box-shadow:0 4px 9px #14243414; }}
                .m5-sensor-label {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.67rem; font-weight:700; letter-spacing:0.05em; }}
                .m5-sensor-value {{ display:block; font-size:1.45rem; font-weight:700; line-height:1.2; margin:5px 0; overflow-wrap:anywhere; }}
                .m5-sensor-meta {{ display:flex; justify-content:space-between; gap:7px; color:{_T['TEXT_MUTED']} !important; font-size:0.66rem; }}
                .m5-simulated-tag {{ color:{_T['ACCENT']} !important; font-size:0.63rem; font-weight:700; letter-spacing:0.05em; white-space:nowrap; }}
                .m5-recorded-at {{ color:{_T['TEXT_MUTED']} !important; font-size:0.7rem; margin:5px 0 15px; }}
                .m5-detection-panel {{ border:1px solid {_T['BORDER']}; border-left:4px solid var(--m5-status); border-radius:5px; background:{_T['SURFACE']}; box-shadow:0 2px 6px #1424340a; padding:12px 15px; margin:8px 0 13px; }}
                .m5-detection-title {{ color:{_T['TEXT_MUTED']} !important; font-size:0.67rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }}
                .m5-detection-state {{ color:var(--m5-status) !important; font-size:1rem; font-weight:700; margin:3px 0; }}
                .m5-detection-detail {{ color:{_T['TEXT_MUTED']} !important; font-size:0.76rem; line-height:1.4; }}
                .m5-chart-heading {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; margin:0 0 4px; }}
                .m5-chart-heading strong {{ font-size:0.83rem; }}
                .m5-chart-current {{ color:{_T['TEXT_MUTED']} !important; font-size:0.72rem; white-space:nowrap; }}
                .m5-records-wrap {{ overflow-x:auto; border:1px solid {_T['BORDER']}; border-radius:5px; margin:6px 0 15px; }}
                .m5-records-table {{ border-collapse:collapse; width:100%; font-size:0.75rem; }}
                .m5-records-table th {{ background:{_T['SURFACE_SUNKEN']}; color:{_T['TEXT_MUTED']} !important; font-size:0.66rem; text-align:left; text-transform:uppercase; letter-spacing:0.04em; padding:8px 10px; }}
                .m5-records-table td {{ border-top:1px solid {_T['BORDER']}; padding:7px 10px; vertical-align:middle; }}
                .m5-records-table tr:hover td {{ background:{_T['SURFACE_SUNKEN']}; }}
                .m5-provenance {{ display:inline-block; border:1px solid {_T['ACCENT']}55; border-radius:10px; background:{_T['ACCENT']}12; color:{_T['ACCENT']} !important; font-size:0.63rem; font-weight:700; padding:2px 7px; white-space:nowrap; }}
                .m5-howto {{ border:1px solid {_T['BORDER']}; border-radius:5px; background:{_T['SURFACE_SUNKEN']}; padding:12px 15px; margin-top:16px; }}
                .m5-howto h3 {{ font-size:0.9rem; margin:0 0 6px; }}
                .m5-howto ol {{ margin:0 0 8px 18px; padding:0; color:{_T['TEXT_MUTED']}; font-size:0.76rem; line-height:1.65; }}
                .m5-howto-warning {{ border-top:1px solid {_T['BORDER']}; color:{_T['TEXT_MUTED']} !important; font-size:0.74rem; padding-top:8px; }}
                div[data-testid="st-key-m5_simulate_normal"] button {{ border-color:{_T['RISK']['LOW']} !important; color:{_T['RISK']['LOW']} !important; }}
                div[data-testid="st-key-m5_simulate_anomalous"] button {{ border-color:{_T['RISK']['MEDIUM']} !important; color:{_T['RISK']['MEDIUM']} !important; }}
                @media (max-width: 760px) {{ .m5-snapshot-grid {{ grid-template-columns:1fr; }} .m5-page-header h1 {{ font-size:1.5rem; }} }}
                .m4-header {{ border-bottom:1px solid {_T['BORDER']}; padding:3px 0 13px; margin:0 auto 13px; max-width:1180px; }}
                .m4-eyebrow {{ color:{_T['ACCENT']} !important; font-size:0.7rem; font-weight:700; letter-spacing:0.09em; text-transform:uppercase; }}
                .m4-header h1 {{ font-size:1.75rem; line-height:1.2; margin:5px 0 3px; }}
                .m4-header p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.87rem; margin:0; }}
                .m4-context {{ border:1px solid {_T['BORDER']}; border-radius:5px; background:{_T['SURFACE']}; padding:11px 14px; margin:8px 0 14px; }}
                .m4-context-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.66rem; font-weight:700; letter-spacing:0.07em; }}
                .m4-context-name {{ display:block; font-size:0.95rem; font-weight:600; margin-top:3px; overflow-wrap:anywhere; }}
                .m4-context-note {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.73rem; margin-top:2px; }}
                .m4-section {{ margin:16px 0 7px; }}
                .m4-section h2 {{ font-size:1.02rem; line-height:1.3; margin:0; }}
                .m4-section p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.76rem; margin:3px 0 0; }}
                .m4-metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; margin:8px 0 12px; }}
                .m4-metric {{ border:1px solid {_T['BORDER']}; border-top:3px solid var(--m4-tone); border-radius:5px; background:{_T['SURFACE']}; padding:10px 12px; min-width:0; box-shadow:0 1px 3px #1424340a; }}
                .m4-metric-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.67rem; font-weight:700; letter-spacing:0.05em; }}
                .m4-metric-value {{ display:block; font-size:1.5rem; font-weight:700; line-height:1.2; margin-top:4px; }}
                .m4-chart-caption {{ color:{_T['TEXT_MUTED']} !important; font-size:0.76rem; margin:0 0 3px; }}
                .m4-completion {{ border:1px solid {_T['BORDER']}; border-left:4px solid {_T['RISK']['LOW']}; border-radius:5px; background:{_T['SURFACE_SUNKEN']}; padding:11px 14px; margin:12px 0 17px; }}
                .m4-completion-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.66rem; font-weight:700; letter-spacing:0.07em; }}
                .m4-completion-main {{ display:flex; align-items:baseline; gap:8px; margin:3px 0 7px; }}
                .m4-completion-main strong {{ font-size:1.35rem; }}
                .m4-completion-main span {{ color:{_T['TEXT_MUTED']} !important; font-size:0.8rem; }}
                .m4-progress-track {{ height:7px; overflow:hidden; border-radius:5px; background:{_T['SURFACE']}; border:1px solid {_T['BORDER']}; }}
                .m4-progress-fill {{ height:100%; border-radius:5px; background:{_T['RISK']['LOW']}; }}
                .m4-progress-caption {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.7rem; margin-top:4px; }}
                .m4-item-heading {{ display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin-bottom:10px; }}
                .m4-item-type {{ font-size:0.9rem; font-weight:700; }}
                .m4-meta-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 14px; }}
                .m4-meta-cell {{ min-width:0; border-bottom:1px solid {_T['BORDER']}; padding:5px 0 7px; }}
                .m4-meta-label {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.64rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; }}
                .m4-meta-value {{ display:block; font-size:0.78rem; margin-top:3px; overflow-wrap:anywhere; }}
                .m4-description {{ font-size:0.8rem; line-height:1.45; margin:10px 0 7px; overflow-wrap:anywhere; }}
                .m4-transition-label {{ color:{_T['ACCENT']} !important; font-size:0.68rem; font-weight:700; letter-spacing:0.06em; margin:10px 0 2px; }}
                .m4-transition-note {{ color:{_T['TEXT_MUTED']} !important; font-size:0.73rem; margin:0 0 8px; }}
                .m4-raw-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.73rem; }}
                @media (max-width: 760px) {{ .m4-metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .m4-meta-grid {{ grid-template-columns:1fr; }} .m4-header h1 {{ font-size:1.5rem; }} }}
                .map-header,.alerts-header,.m0-header,.m1-header,.contractor-header,.grievance-header,.voice-header,.approval-header,.report-header,.settings-header,.audit-header {{ max-width:1320px; margin:0 auto 12px; border-bottom:1px solid {_T['BORDER']}; padding:3px 0 12px; }}
                .map-eyebrow,.alerts-eyebrow,.m0-eyebrow,.m1-eyebrow,.contractor-eyebrow,.grievance-eyebrow,.voice-eyebrow,.approval-eyebrow,.report-eyebrow,.settings-eyebrow,.audit-eyebrow {{ color:{_T['ACCENT']} !important; font-size:0.68rem; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; }}
                .map-header h1,.alerts-header h1,.m0-header h1,.m1-header h1,.contractor-header h1,.grievance-header h1,.voice-header h1,.approval-header h1,.report-header h1,.settings-header h1,.audit-header h1 {{ font-size:1.65rem; line-height:1.2; margin:4px 0; }}
                .map-header p,.alerts-header p,.m0-header p,.m1-header p,.contractor-header p,.grievance-header p,.voice-header p,.approval-header p,.report-header p,.settings-header p,.audit-header p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.83rem; margin:0; }}
                .map-summary,.alerts-summary,.m0-summary,.m1-summary,.contractor-summary,.grievance-summary,.audit-summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; margin:10px 0 13px; }}
                .map-summary-five {{ grid-template-columns:repeat(5,minmax(0,1fr)); }}
                .map-metric,.alerts-metric,.m0-metric,.m1-metric,.contractor-metric,.grievance-metric,.audit-metric {{ min-width:0; border:1px solid {_T['BORDER']}; border-top:3px solid var(--metric-tone); border-radius:5px; background:{_T['SURFACE']}; padding:9px 12px; box-shadow:0 1px 3px #1424340a; }}
                .map-metric-label,.alerts-metric-label,.m0-metric-label,.m1-metric-label,.contractor-metric-label,.grievance-metric-label,.audit-metric-label {{ color:{_T['TEXT_MUTED']} !important; font-size:0.65rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; }}
                .map-metric-value,.alerts-metric-value,.m0-metric-value,.m1-metric-value,.contractor-metric-value,.grievance-metric-value,.audit-metric-value {{ display:block; font-size:1.35rem; font-weight:700; line-height:1.2; margin-top:4px; }}
                .map-card,.alerts-card,.m0-card,.m1-card,.contractor-card,.grievance-card,.voice-card,.approval-card,.report-card,.settings-card,.audit-card {{ border:1px solid {_T['BORDER']}; border-radius:5px; background:{_T['SURFACE']}; padding:12px 14px; box-shadow:0 1px 4px #1424340a; margin:7px 0; }}
                .map-section,.alerts-section,.m0-section,.m1-section,.contractor-section,.grievance-section,.voice-section,.approval-section,.report-section,.settings-section,.audit-section {{ margin:15px 0 7px; }}
                .map-section h2,.alerts-section h2,.m0-section h2,.m1-section h2,.contractor-section h2,.grievance-section h2,.voice-section h2,.approval-section h2,.report-section h2,.settings-section h2,.audit-section h2 {{ font-size:1rem; line-height:1.3; margin:0; }}
                .map-section p,.alerts-section p,.m0-section p,.m1-section p,.contractor-section p,.grievance-section p,.voice-section p,.approval-section p,.report-section p,.settings-section p,.audit-section p {{ color:{_T['TEXT_MUTED']} !important; font-size:0.74rem; margin:2px 0 0; }}
                .map-note,.alerts-health,.m0-health,.m1-note,.contractor-note,.grievance-note,.voice-note,.approval-note,.report-note,.settings-note,.audit-note {{ border:1px solid {_T['BORDER']}; border-left:3px solid {_T['ACCENT']}; border-radius:4px; background:{_T['SURFACE_SUNKEN']}; padding:9px 12px; margin:9px 0 13px; color:{_T['TEXT_MUTED']} !important; font-size:0.75rem; line-height:1.4; }}
                .map-legend,.map-detail-grid,.alerts-health-grid,.alerts-workspace,.m0-register-grid,.m1-actions,.contractor-detail-grid,.grievance-workspace,.voice-workflow,.voice-actions,.approval-workflow,.approval-stages,.settings-grid,.audit-integrity-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
                .map-provenance,.page-context-badge,.workflow-badge {{ display:inline-block; border:1px solid {_T['BORDER']}; border-radius:12px; background:{_T['SURFACE_SUNKEN']}; color:{_T['TEXT_MUTED']} !important; font-size:0.64rem; font-weight:700; letter-spacing:0.04em; padding:3px 8px; }}
                .map-detail-value,.contractor-detail-value {{ display:block; font-size:0.88rem; font-weight:600; overflow-wrap:anywhere; }}
                .map-detail-label,.contractor-detail-label {{ color:{_T['TEXT_MUTED']} !important; display:block; font-size:0.63rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:3px; }}
                .map-shap-list {{ display:grid; gap:6px; }}
                .map-shap-row {{ display:grid; grid-template-columns:minmax(130px,1fr) minmax(80px,2fr) auto; gap:8px; align-items:center; font-size:0.72rem; }}
                .map-shap-track {{ position:relative; height:7px; border-radius:5px; background:linear-gradient(90deg, transparent calc(50% - 1px), {_T['BORDER']} calc(50% - 1px), {_T['BORDER']} calc(50% + 1px), {_T['SURFACE_SUNKEN']} calc(50% + 1px)); overflow:hidden; }}
                .map-shap-fill {{ position:absolute; top:0; height:100%; border-radius:5px; }}
                .alerts-health-grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
                .alerts-health-item {{ border:1px solid {_T['BORDER']}; border-radius:4px; background:{_T['SURFACE_SUNKEN']}; padding:8px 10px; }}
                .alerts-queue-item {{ border:1px solid {_T['BORDER']}; border-left:4px solid var(--alert-tone); border-radius:5px; background:{_T['SURFACE']}; padding:11px 13px; margin:7px 0; }}
                .alerts-category-row {{ display:grid; grid-template-columns:1fr auto; align-items:center; gap:8px; border-bottom:1px solid {_T['BORDER']}; padding:7px 0; font-size:0.78rem; }}
                .m0-status-list,.audit-status-list {{ display:flex; flex-wrap:wrap; gap:7px; }}
                .m0-status-pill {{ border:1px solid {_T['BORDER']}; border-radius:4px; padding:5px 8px; font-size:0.7rem; }}
                .m0-action {{ border-left:4px solid {_T['RISK']['MEDIUM']}; background:{_T['SURFACE_SUNKEN']}; padding:10px 12px; border-radius:4px; margin:10px 0; }}
                .m4-progress-track,.m1-progress-track {{ height:6px; border-radius:5px; background:{_T['SURFACE_SUNKEN']}; overflow:hidden; }}
                .m1-workflow,.voice-workflow {{ grid-template-columns:repeat(5,minmax(0,1fr)); }}
                .m1-step,.voice-step {{ text-align:center; border:1px solid {_T['BORDER']}; border-radius:5px; padding:8px 5px; background:{_T['SURFACE']}; font-size:0.68rem; font-weight:600; }}
                .m1-document-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
                .contractor-status {{ display:inline-block; border-radius:12px; padding:3px 9px; font-size:0.67rem; font-weight:700; background:{_T['SURFACE_SUNKEN']}; border:1px solid {_T['BORDER']}; }}
                .contractor-engagement-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; margin-top:8px; }}
                .grievance-item {{ border:1px solid {_T['BORDER']}; border-left:4px solid var(--grievance-tone); border-radius:5px; background:{_T['SURFACE']}; padding:11px 13px; margin:7px 0; }}
                .voice-result-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
                .voice-step::before {{ display:block; color:{_T['ACCENT']}; font-weight:700; margin-bottom:3px; }}
                .approval-step {{ border:1px solid {_T['BORDER']}; border-radius:5px; padding:9px 10px; background:{_T['SURFACE']}; }}
                .audit-hash {{ font-family:{FONT_MONO}; font-size:0.68rem; background:{_T['SURFACE_SUNKEN']}; border:1px solid {_T['BORDER']}; border-radius:3px; padding:2px 5px; }}
                .audit-action {{ display:inline-block; font-family:{FONT_MONO}; font-size:0.66rem; border:1px solid {_T['BORDER']}; border-radius:4px; padding:2px 6px; background:{_T['SURFACE_SUNKEN']}; }}
                @media (max-width: 900px) {{ .map-summary,.alerts-summary,.m0-summary,.m1-summary,.contractor-summary,.grievance-summary,.audit-summary,.map-summary-five {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .alerts-workspace,.grievance-workspace,.voice-actions,.approval-workflow,.settings-grid {{ grid-template-columns:1fr; }} .alerts-health-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
                @media (max-width: 640px) {{ .map-summary,.alerts-summary,.m0-summary,.m1-summary,.contractor-summary,.grievance-summary,.audit-summary,.map-legend,.map-detail-grid,.m0-register-grid,.m1-actions,.contractor-detail-grid,.voice-result-grid,.settings-grid,.audit-integrity-grid {{ grid-template-columns:1fr; }} .m1-workflow,.voice-workflow {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .contractor-engagement-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
                :root {{
                  color-scheme: {"dark" if _THEME_MODE == "dark" else "light"};
                  --ax-signal: {"#D8EF66" if _THEME_MODE == "dark" else "#819322"};
                  --ax-shadow: {"#00000055" if _THEME_MODE == "dark" else "#25302718"};
                }}
                .stApp {{
                  background-color:{_T['SURFACE']};
                  background-image:radial-gradient(ellipse at 88% 0%, {_T['ACCENT']}16, transparent 31%),
                                   linear-gradient(135deg, {_T['SURFACE']} 0%, {_T['SURFACE_SUNKEN']} 100%);
                  background-attachment:fixed;
                }}
                [data-testid="stAppViewContainer"] {{ background:transparent; }}
                .block-container {{ max-width:1560px !important; padding-top:1.7rem !important; padding-bottom:3rem !important; }}
                header[data-testid="stHeader"] {{ background:transparent; }}
                section[data-testid="stSidebar"] {{
                  background:linear-gradient(165deg, {_T['SURFACE_SUNKEN']}, {_T['SURFACE']});
                  border-right:1px solid {_T['BORDER']};
                  box-shadow:8px 0 32px var(--ax-shadow);
                }}
                section[data-testid="stSidebar"] > div {{ border-right:0; }}
                section[data-testid="stSidebar"] .overview-sidebar-brand {{
                  padding:12px 0 14px; margin-bottom:10px;
                  border-bottom:1px solid {_T['BORDER']};
                }}
                section[data-testid="stSidebar"] .overview-sidebar-brand strong {{
                  font-size:1.22rem !important; letter-spacing:.11em;
                }}
                section[data-testid="stSidebar"] .overview-sidebar-brand strong::before {{
                  content:""; display:inline-block; width:8px; height:19px;
                  margin-right:10px; vertical-align:-3px; transform:skew(-15deg);
                  background:var(--ax-signal); box-shadow:5px 0 0 {_T['ACCENT']};
                }}
                section[data-testid="stSidebar"] .overview-sidebar-subtitle {{
                  overflow-wrap:anywhere; line-height:1.5; padding:8px 9px;
                  border-left:2px solid {_T['ACCENT']}; background:{_T['SURFACE']};
                }}
                section[data-testid="stSidebar"] .overview-nav-group {{
                  margin:19px 0 6px !important; padding-left:2px;
                  color:{_T['TEXT_MUTED']} !important; font-family:{FONT_MONO};
                  font-size:.61rem !important; letter-spacing:.16em !important;
                }}
                section[data-testid="stSidebar"] div.stButton > button {{
                  min-height:2.25rem; border-radius:2px !important;
                  font-size:.8rem; letter-spacing:.01em;
                  transition:transform .16s ease, border-color .16s ease, background .16s ease;
                }}
                section[data-testid="stSidebar"] div.stButton > button:hover {{
                  transform:translateX(3px); border-color:{_T['ACCENT']} !important;
                }}
                section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {{
                  box-shadow:inset 3px 0 0 var(--ax-signal), 0 4px 12px var(--ax-shadow);
                  letter-spacing:.025em;
                }}
                .overview-heading {{
                  position:relative; overflow:hidden; min-height:190px;
                  padding:24px 24px 22px !important; margin:0 0 20px !important;
                  border:1px solid {_T['BORDER']}; border-bottom:3px solid {_T['ACCENT']} !important;
                  background:linear-gradient(112deg, {_T['SURFACE']} 0%, {_T['SURFACE']} 67%, {_T['SURFACE_SUNKEN']} 100%);
                  box-shadow:0 12px 34px var(--ax-shadow);
                  animation:ax-arrive .55s cubic-bezier(.2,.7,.25,1) both;
                }}
                .overview-heading::after {{
                  content:""; position:absolute; top:-42px; right:6%; width:190px; height:240px;
                  border:1px solid {_T['ACCENT']}38; transform:rotate(28deg) skewY(-12deg);
                  background:repeating-linear-gradient(135deg, transparent 0 12px, {_T['ACCENT']}0D 12px 13px);
                  pointer-events:none;
                }}
                .overview-brand {{
                  display:flex; align-items:center; gap:8px;
                  color:{_T['ACCENT']} !important; font-family:{FONT_MONO};
                  font-size:.67rem !important; letter-spacing:.16em !important;
                }}
                .overview-brand::before {{
                  content:""; width:7px; height:7px; border-radius:50%;
                  background:var(--ax-signal); box-shadow:0 0 0 3px {_T['ACCENT']}1C;
                }}
                .overview-identity {{ font-family:{FONT_MONO}; font-size:.69rem !important; letter-spacing:.015em; }}
                .overview-heading h1 {{
                  position:relative; z-index:1; width:max-content; max-width:100%;
                  margin:19px 0 6px !important; font-size:clamp(2.6rem,5vw,4.4rem) !important;
                  font-weight:700 !important; letter-spacing:-.075em; line-height:.95 !important;
                }}
                .overview-heading p {{ position:relative; z-index:1; max-width:620px; font-size:.9rem !important; }}
                .overview-user {{
                  margin:2px 0 0 auto; padding:14px 0 0 13px !important;
                  border-left:2px solid var(--ax-signal); text-align:left !important;
                }}
                .overview-user strong {{ font-family:{FONT_MONO}; font-size:.75rem !important; }}
                .overview-user span {{ text-transform:uppercase; letter-spacing:.12em; font-size:.65rem !important; }}
                .overview-section {{ margin:25px 0 9px !important; }}
                .overview-section h2 {{
                  font-family:{FONT_MONO}; font-size:.76rem !important;
                  letter-spacing:.12em; text-transform:uppercase;
                }}
                .overview-section p {{ font-size:.75rem !important; }}
                .overview-kpi-grid {{ gap:9px !important; margin-bottom:18px !important; }}
                .overview-kpi {{
                  position:relative; overflow:hidden; min-height:128px;
                  border-radius:2px !important; border-top:1px solid {_T['BORDER']} !important;
                  border-left:3px solid var(--kpi-tone) !important;
                  background:linear-gradient(145deg, {_T['SURFACE']}, {_T['SURFACE_SUNKEN']}) !important;
                  box-shadow:0 5px 16px var(--ax-shadow) !important;
                  padding:14px 15px 12px !important;
                  transition:transform .18s ease, box-shadow .18s ease !important;
                  animation:ax-arrive .45s cubic-bezier(.2,.7,.25,1) both;
                }}
                .overview-kpi:nth-child(2) {{ animation-delay:.04s; }}
                .overview-kpi:nth-child(3) {{ animation-delay:.08s; }}
                .overview-kpi:nth-child(4) {{ animation-delay:.12s; }}
                .overview-kpi:hover {{ transform:translateY(-3px) !important; box-shadow:0 10px 24px var(--ax-shadow) !important; }}
                .overview-kpi-value {{ margin-top:13px !important; font-size:2rem !important; letter-spacing:-.07em; }}
                .overview-kpi-label {{ font-family:{FONT_MONO}; letter-spacing:.08em !important; }}
                .overview-status-strip {{
                  border-radius:2px !important; border-left:3px solid var(--ax-signal) !important;
                  background:{_T['SURFACE']} !important; box-shadow:0 5px 16px var(--ax-shadow);
                  padding:13px 15px !important;
                }}
                .overview-status-item {{ padding:5px 7px; border-left:1px solid {_T['BORDER']}; }}
                .overview-status-dot {{ box-shadow:0 0 0 3px {_T['ACCENT']}18; }}
                .overview-panel,.overview-mine-row,.overview-audit-wrap {{
                  border-radius:2px !important; box-shadow:0 5px 16px var(--ax-shadow);
                }}
                [data-testid="stVerticalBlockBorderWrapper"] {{
                  border-radius:2px !important; box-shadow:0 6px 20px var(--ax-shadow);
                }}
                .stButton button,.stFormSubmitButton button,button[kind] {{
                  min-height:2.45rem; border-radius:2px !important;
                  font-weight:600; transition:transform .16s ease, box-shadow .16s ease, background .16s ease;
                }}
                .stButton button:hover,.stFormSubmitButton button:hover,button[kind]:hover {{
                  transform:translateY(-1px); box-shadow:0 5px 14px var(--ax-shadow);
                }}
                input,textarea,[data-baseweb="select"] > div {{
                  border-radius:2px !important;
                }}
                input:focus,textarea:focus,[data-baseweb="select"]:focus-within {{
                  box-shadow:0 0 0 2px {_T['ACCENT']}42 !important;
                }}
                [data-testid="stDataFrame"],[data-testid="stTable"] {{
                  border:1px solid {_T['BORDER']}; box-shadow:0 6px 18px var(--ax-shadow);
                }}
                code,.anthryx-id,.identifier {{ font-variant-numeric:tabular-nums; }}
                ::selection {{ background:{_T['ACCENT']}; color:#fff; }}
                @keyframes ax-arrive {{
                  from {{ opacity:0; transform:translateY(9px); }}
                  to {{ opacity:1; transform:translateY(0); }}
                }}
                @media (max-width: 640px) {{
                  .block-container {{ padding:1rem .8rem 2rem !important; }}
                  .overview-heading {{ min-height:0; padding:18px 16px !important; }}
                  .overview-heading h1 {{ font-size:2.7rem !important; }}
                  .overview-heading::after {{ right:-100px; }}
                  .overview-user {{ padding:0 0 0 10px !important; }}
                  .overview-kpi {{ min-height:108px; }}
                }}
                @media (prefers-reduced-motion: reduce) {{
                  *,*::before,*::after {{ animation-duration:.01ms !important; animation-iteration-count:1 !important; scroll-behavior:auto !important; transition-duration:.01ms !important; }}
                }}
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

DEMO_ACCOUNTS = {
    "Admin": "demo.admin@example.com",
    "Manager": "demo.manager@example.com",
    "Inspector": "demo.inspector@example.com",
}


def _client() -> ApiClient:
    if "client" not in st.session_state:
        st.session_state.client = ApiClient()
    return st.session_state.client


def render_overview(client: ApiClient, user: dict):
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

    scored = [m for m in overview if m["risk_score"] is not None]
    m5_scored = sum(1 for m in overview if m.get("m5_is_anomaly") is not None)

    try:
        audit = client.get("/api/v1/audit", limit=5)
    except ApiError:
        audit = None

    left, right = st.columns([4, 1], gap="large")
    with left:
        st.markdown(
            '<div class="overview-heading">'
            '<div class="overview-brand">ANTHRYX AI</div>'
            '<div class="overview-identity">Coal mine compliance and governance · SIH26024 · Team DATA_HELIX</div>'
            '<h1>Overview</h1>'
            '<p>Operational risk, compliance status and pending actions across monitored mines.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            '<div class="overview-user">'
            f'<strong>{escape(str(user.get("email", "Signed-in user")))}</strong>'
            f'<span>{escape(str(user.get("role", ""))).replace("_", " ")}</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    section_header("Executive summary", "Live counts from the mines, risk, CAPA and governance records.", _T)
    overview_kpi_grid([
        {"label": "MINES IN SCOPE", "value": len(mines), "status": "IN SCOPE",
         "support": "Mines visible to this role", "tone": "neutral"},
        {"label": "HIGH-RISK MINES", "value": high_risk,
         "status": "REVIEW" if high_risk else "CLEAR",
         "support": "Requires attention" if high_risk else "No high-risk mines", "tone": "high" if high_risk else "good"},
        {"label": "M5 ANOMALIES ACTIVE", "value": anomalous,
         "status": "ACTIVE" if anomalous else "CLEAR",
         "support": "SIMULATED telemetry only", "tone": "warn" if anomalous else "good"},
        {"label": "SCORES NEEDING REBUILD", "value": stale,
         "status": "REBUILD" if stale else "CURRENT",
         "support": "Risk inputs changed since scoring" if stale else "No rebuild currently flagged", "tone": "warn" if stale else "good"},
    ], _T)

    section_header("Compliance & action", "Corrective actions, incidents and verification status.", _T)
    overview_kpi_grid([
        {"label": "OPEN CAPA ITEMS", "value": open_capa,
         "status": "PENDING" if open_capa else "CLEAR",
         "support": "Action pending" if open_capa else "No open actions", "tone": "warn" if open_capa else "good"},
        {"label": "OVERDUE CAPA", "value": overdue_capa,
         "status": "OVERDUE" if overdue_capa else "ON TRACK",
         "support": "Past due" if overdue_capa else "No overdue actions", "tone": "bad" if overdue_capa else "good"},
        {"label": "CLOSED / VERIFIED CAPA", "value": closed_capa,
         "status": "VERIFIED" if closed_capa else "NO CLOSURES",
         "support": "Verified closure records", "tone": "good" if closed_capa else "neutral"},
        {"label": "RECENT INCIDENTS", "value": recent_incidents,
         "status": "RECORDED" if recent_incidents else "NONE",
         "support": "Incident evidence on record", "tone": "neutral"},
    ], _T)

    section_header("Actions & governance", "Approvals, grievance SLAs and contractor standing.", _T)
    overview_kpi_grid([
        {"label": "PENDING APPROVALS", "value": pending_approvals,
         "status": "PENDING" if pending_approvals else "CLEAR",
         "support": "Awaiting a decision" if pending_approvals else "No pending decisions", "tone": "warn" if pending_approvals else "good"},
        {"label": "GRIEVANCES · SLA BREACHED", "value": breached_grievances,
         "status": "BREACHED" if breached_grievances else "ON TRACK",
         "support": "Requires follow-up" if breached_grievances else "No breached SLAs", "tone": "bad" if breached_grievances else "good"},
        {"label": "TOTAL GRIEVANCES", "value": len(grievances),
         "status": "RECORDED" if grievances else "NONE",
         "support": "Worker and community records", "tone": "neutral"},
        {"label": "DEBARRED CONTRACTORS", "value": debarred_contractors,
         "status": "ACTIVE" if debarred_contractors else "NONE",
         "support": "Debarred in visible scope" if debarred_contractors else "No debarred contractors", "tone": "bad" if debarred_contractors else "good"},
    ], _T)

    status_items = [
        ("API", "Connected", "Mines and risk overview loaded", _T["RISK"]["LOW"]),
        ("M3 risk scores", f"{len(scored)} / {len(mines)} scored", "Existing mine scores", _T["ACCENT"]),
        ("M5 telemetry", f"{m5_scored} mines scored" if m5_scored else "No readings", "Separate from M3 risk", _T["ACCENT"]),
        ("Audit ledger", "Available" if audit is not None else "Unavailable",
         f"{len(audit)} recent entries" if audit is not None else "No audit response", _T["RISK"]["LOW"] if audit is not None else _T["TEXT_MUTED"]),
    ]
    status_html = "".join(
        '<div class="overview-status-item">'
        f'<span class="overview-status-dot" style="background:{color}"></span>'
        f'<div class="overview-status-copy"><strong>{escape(label)} · {escape(value)}</strong>'
        f'<span>{escape(detail)}</span></div></div>'
        for label, value, detail, color in status_items
    )
    st.markdown(
        '<div class="overview-status-strip"><div class="overview-section" style="grid-column:1/-1;margin:0">'
        '<h2>SYSTEM STATUS</h2></div>' + status_html + '</div>',
        unsafe_allow_html=True,
    )

    section_header("MINE RISK OVERVIEW", "Operational risk score by monitored mine. Scores are M3 risk signals, not calibrated accident probabilities.", _T)
    if scored:
        import pandas as pd
        risk_order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        risk_palette = [_T["RISK"][level] for level in risk_order]
        chart_df = pd.DataFrame({
            "Mine": [m["name"] for m in scored],
            "Code": [m["code"] for m in scored],
            "M3 Operational Risk Score": [m["risk_score"] for m in scored],
            "Risk category": [m["risk_category"] for m in scored],
        })
        import altair as alt
        chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusEnd=3, size=20)
            .encode(
                y=alt.Y("Mine:N", title=None, sort=alt.SortField(field="M3 Operational Risk Score", order="descending"),
                        axis=alt.Axis(labelLimit=250, ticks=False, domain=False)),
                x=alt.X("M3 Operational Risk Score:Q", title="M3 Operational Risk Score (0–1)",
                        scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".2f", tickCount=6)),
                color=alt.Color("Risk category:N", title="Risk level",
                                scale=alt.Scale(domain=risk_order, range=risk_palette), legend=None),
                tooltip=[
                    alt.Tooltip("Mine:N", title="Mine"), alt.Tooltip("Code:N", title="Mine code"),
                    alt.Tooltip("M3 Operational Risk Score:Q", title="M3 Operational Risk Score", format=".3f"),
                    alt.Tooltip("Risk category:N", title="Risk level"),
                ],
            )
            .properties(height=max(190, min(340, 38 * len(scored))))
            .configure(background=_T["SURFACE"])
            .configure_view(strokeWidth=0)
            .configure_axis(
                labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                gridColor=_T["BORDER"], domainColor=_T["BORDER"],
                labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=11,
            )
        )
        with st.container(border=True):
            st.altair_chart(chart, use_container_width=True, theme=None)
    else:
        empty_state("No mine has been scored yet - build features on the M3 Risk page.", _T)

    section_header("Mines requiring attention", "Risk level, M3 score and open action counts for every mine in scope.", _T)
    sorted_overview = sorted(overview, key=lambda m: m["risk_score"] or -1, reverse=True)
    mine_rows = []
    for m in sorted_overview:
        category = str(m.get("risk_category") or "").upper()
        badge = severity_badge(category, _T)
        score = m.get("risk_score")
        risk_tone = _T["RISK"].get(category, _T["TEXT_MUTED"])
        meter_width = max(0.0, min(100.0, float(score) * 100)) if score is not None else 0.0
        score_label = f"{float(score):.3f}" if score is not None else "Not yet scored"
        mine_rows.append(
            '<div class="overview-mine-row"><div>'
            f'<div class="overview-mine-title">{badge}<strong>{escape(str(m["name"]))}</strong>'
            f'<span class="overview-mine-code">{escape(str(m["code"]))}</span></div>'
            f'<div class="overview-mine-meta">{m["open_capa_count"]} open CAPA · {m["overdue_capa_count"]} overdue</div>'
            '</div><div>'
            f'<div class="overview-mine-meta">M3 Operational Risk Score <strong>{escape(score_label)}</strong></div>'
            f'<div class="overview-risk-meter"><div class="overview-risk-fill" style="width:{meter_width:.1f}%;background:{risk_tone}"></div></div>'
            '</div></div>'
        )
    st.markdown(f'<div class="overview-mine-list">{"".join(mine_rows)}</div>', unsafe_allow_html=True)

    st.markdown(
        '<p class="overview-identity">M5 sensor-anomaly information is shown separately and is never combined with the M3 operational risk score.</p>',
        unsafe_allow_html=True,
    )

    section_header("Recent audit activity", "Latest recorded actions from the existing audit endpoint.", _T)
    if audit is None:
        st.caption("Audit activity unavailable for this role.")
    elif audit:
        audit_rows = "".join(
            '<tr>'
            f'<td class="overview-audit-seq">{escape(str(a["seq"]))}</td>'
            f'<td><span class="overview-audit-action">{escape(str(a["action"]))}</span></td>'
            f'<td>{escape(str(a["entity_type"]))}</td>'
            f'<td>{escape(format_timestamp(a["timestamp"]))}</td>'
            '</tr>'
            for a in audit
        )
        st.markdown(
            '<div class="overview-audit-wrap"><table class="overview-audit-table">'
            '<thead><tr><th>Seq</th><th>Action</th><th>Entity</th><th>Timestamp</th></tr></thead>'
            f'<tbody>{audit_rows}</tbody></table></div>',
            unsafe_allow_html=True,
        )
    else:
        empty_state("No audit activity has been recorded yet.", _T)


def render_risk(client: ApiClient):
    try:
        status = client.get("/api/v1/risk/model-status")
    except ApiError as exc:
        error_state(f"Could not reach the model status endpoint: {exc}", _T)
        return

    model = status["model"]
    model_hash = str(model.get("sha256") or "-")
    header_left, header_right = st.columns([3, 1], gap="large")
    with header_left:
        st.markdown(
            '<div class="m3-header">'
            '<div class="m3-eyebrow">M3 · Risk Intelligence</div>'
            '<h1>Operational Risk Assessment</h1>'
            '<p>Supervised accident-risk score. A ranking/prioritisation signal - '
            "not asserted as a calibrated probability outside the model's MSHA test population.</p>"
            '</div>',
            unsafe_allow_html=True,
        )
    with header_right:
        st.markdown(
            '<div class="m3-status-card">'
            '<div class="m3-status-label">Model status</div>'
            f'<div class="m3-status-value">{escape(str(model["status"]))}</div>'
            f'<span class="m3-status-meta">Model SHA-256<br><code title="{escape(model_hash)}">{escape(model_hash)}</code></span>'
            '</div>',
            unsafe_allow_html=True,
        )

    # Preserve the existing status panel's artifact identity and source value.
    st.markdown(
        f'<div class="m3-status-meta">Status source: {escape(str(model["status"]))} · '
        f'version/hash: <code title="{escape(model_hash)}">{escape(model_hash[:16])}...</code></div>',
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
    with st.container(border=True):
        st.markdown(
            '<div class="m3-assessment-intro">'
            '<h2>Mine Assessment</h2>'
            '<p>Select a mine to inspect its current operational risk signal.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        assessment_col, action_col = st.columns([1, 1.35], gap="large", vertical_alignment="bottom")
        with assessment_col:
            chosen = st.selectbox("Mine", list(mine_names))
        mine_id = mine_names[chosen]
        with action_col:
            rebuild = st.button(
                "Build / refresh features from live application data",
                use_container_width=True,
            )
        if rebuild:
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
    score = result["risk_score"]
    score_value = float(score)
    score_width = max(0.0, min(100.0, score_value * 100))
    score_color = _T["RISK"]["CRITICAL"] if cat == "HIGH" else risk_color(cat, _THEME_MODE)
    st.markdown(
        f'<div class="m3-score-card" style="--m3-risk:{score_color}">'
        '<div class="m3-score-top"><div>'
        '<div class="m3-score-label">Current M3 Risk Signal</div>'
        f'<div class="m3-score-value">{escape(str(score))}</div>'
        '</div>'
        f'<span class="m3-category">{escape(str(cat))}</span></div>'
        '<div class="m3-scale-head"><span>M3 score scale · 0–1</span><span>Not a probability</span></div>'
        f'<div class="m3-scale-track"><div class="m3-scale-fill" style="width:{score_width:.5f}%"></div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    _model_version_display = result['model_version'].replace("\\", "/").rsplit("/", 1)[-1]
    st.markdown(
        '<div class="m3-callout"><strong>How to read this signal</strong>'
        f'<span>{escape(str(result["vocabulary_note"]))}</span></div>',
        unsafe_allow_html=True,
    )

    explanation = result.get("explanation")
    explanation_method = result.get("explanation_method") or "Unavailable"
    context_items = [
        ("Model", str(model["status"])),
        ("Signal type", "Operational risk prioritisation"),
        ("Interpretability", str(explanation_method) if explanation else "Unavailable"),
        ("Assessment", "Mine-specific"),
    ]
    context_html = "".join(
        '<div class="m3-context-card">'
        f'<span class="m3-context-label">{escape(label)}</span>'
        f'<span class="m3-context-value">{escape(value)}</span>'
        '</div>'
        for label, value in context_items
    )
    st.markdown(f'<div class="m3-context-grid">{context_html}</div>', unsafe_allow_html=True)
    st.caption(
        f"Model version: {_model_version_display} - artifact hash: {result['artifact_hash'][:16]}..."
    )
    if result.get("capa_created"):
        st.success(f"A new RISK_ALERT CAPA was created: {result['capa_id']}")
    elif result.get("capa_id"):
        st.caption(f"An active RISK_ALERT CAPA already covers this mine: {result['capa_id']}")

    st.markdown(
        '<div class="m3-section"><h2>Why this mine is receiving this signal</h2>'
        '<p>Per-instance SHAP contributions for this mine; positive values increase the model score and negative values decrease it.</p></div>',
        unsafe_allow_html=True,
    )
    if explanation is None:
        empty_state("No SHAP explanation is available for this prediction.", _T)
    else:
        st.caption(f"Method: {explanation_method} (per-instance, this mine only - not global importance)")
        rows = sorted(explanation.items(), key=lambda kv: abs(kv[1]), reverse=True)
        import altair as alt
        import pandas as pd

        max_magnitude = max((abs(float(value)) for _, value in rows), default=0.0)
        chart_extent = max_magnitude * 1.12 if max_magnitude else 0.01
        shap_data = pd.DataFrame([
            {
                "Feature": feature,
                "SHAP contribution": value,
                "Order": index,
                "Direction": (
                    "Increases score" if value > 0 else
                    "Decreases score" if value < 0 else "No contribution"
                ),
            }
            for index, (feature, value) in enumerate(rows)
        ])
        bar_layer = alt.Chart(shap_data).mark_bar(size=18, cornerRadiusEnd=2).encode(
            y=alt.Y(
                "Feature:N", title=None,
                sort=alt.SortField(field="Order", order="ascending"),
                axis=alt.Axis(labelLimit=280, ticks=False, domain=False),
            ),
            x=alt.X(
                "SHAP contribution:Q", title="SHAP contribution to model score",
                scale=alt.Scale(domain=[-chart_extent, chart_extent]),
                axis=alt.Axis(grid=True, tickCount=5, format=".3g"),
            ),
            color=alt.Color(
                "Direction:N", title=None,
                scale=alt.Scale(
                    domain=["Increases score", "Decreases score", "No contribution"],
                    range=[_T["ACCENT"], _T["RISK"]["LOW"], _T["TEXT_MUTED"]],
                ),
                legend=alt.Legend(orient="top", direction="horizontal"),
            ),
            tooltip=[
                alt.Tooltip("Feature:N", title="Feature"),
                alt.Tooltip("SHAP contribution:Q", title="Exact SHAP contribution"),
                alt.Tooltip("Direction:N", title="Effect"),
            ],
        )
        zero_rule = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(
            color=_T["TEXT_MUTED"], opacity=0.75, strokeDash=[3, 3],
        ).encode(x="zero:Q")
        shap_chart = (bar_layer + zero_rule).properties(
            height=max(250, min(520, 34 * len(rows))),
        ).configure(
            background=_T["SURFACE"],
        ).configure_view(
            strokeWidth=0,
        ).configure_axis(
            labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
            gridColor=_T["BORDER"], domainColor=_T["BORDER"],
            labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=11,
        ).configure_legend(
            labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
            labelFont=FONT_UI, titleFont=FONT_UI,
        )
        with st.container(border=True):
            st.altair_chart(shap_chart, use_container_width=True)

        table_rows = "".join(
            '<tr>'
            f'<td class="m3-feature-name">{escape(str(feature))}</td>'
            f'<td class="m3-feature-value {"m3-positive" if value > 0 else "m3-negative" if value < 0 else "m3-zero"}">{escape(str(value))}</td>'
            '</tr>'
            for feature, value in rows
        )
        st.markdown(
            '<div class="m3-feature-table-wrap"><table class="m3-feature-table">'
            '<thead><tr><th>Feature</th><th style="text-align:right">SHAP contribution</th></tr></thead>'
            f'<tbody>{table_rows}</tbody></table></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="m3-section"><h2>Historical M3 scoring activity</h2>'
        '<p>All recorded M3 scores for this mine, in chronological order.</p></div>',
        unsafe_allow_html=True,
    )
    try:
        history = client.get(f"/api/v1/risk/mines/{mine_id}/history")
    except ApiError as exc:
        history = []
    if len(history) >= 2:
        import altair as alt
        import pandas as pd

        ordered_history = sorted(history, key=lambda item: item["scored_at"])
        trend_data = pd.DataFrame([
            {
                "Scored at": pd.to_datetime(item["scored_at"], utc=True),
                "Recorded timestamp": item["scored_at"],
                "M3 risk score": item["risk_score"],
                "Risk category": item["risk_category"],
            }
            for item in ordered_history
        ])
        score_values = [float(item["risk_score"]) for item in ordered_history]
        if max(score_values) - min(score_values) <= 0.01:
            st.info(
                "Recorded scores are closely clustered. The chart keeps the full 0–1 score scale "
                "so small differences are not visually exaggerated."
            )
        trend_chart = alt.Chart(trend_data).mark_line(
            color=_T["ACCENT"], strokeWidth=2.5,
            point=alt.OverlayMarkDef(filled=True, size=55, color=_T["ACCENT"]),
        ).encode(
            x=alt.X(
                "Scored at:T", title="Scored at", sort="ascending",
                axis=alt.Axis(
                    format="%d %b %H:%M", labelAngle=-25,
                    labelOverlap="greedy", tickCount=min(7, len(ordered_history)),
                    grid=False,
                ),
            ),
            y=alt.Y(
                "M3 risk score:Q", title="M3 risk score (0–1)",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format=".2f", tickCount=6, grid=True),
            ),
            tooltip=[
                alt.Tooltip("Recorded timestamp:N", title="Recorded at"),
                alt.Tooltip("M3 risk score:Q", title="M3 risk score"),
                alt.Tooltip("Risk category:N", title="Risk category"),
            ],
        ).properties(
            height=330,
        ).configure(
            background=_T["SURFACE"],
        ).configure_view(
            strokeWidth=0,
        ).configure_axis(
            labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
            gridColor=_T["BORDER"], domainColor=_T["BORDER"],
            labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=11,
        )
        with st.container(border=True):
            st.altair_chart(trend_chart, use_container_width=True)
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
    try:
        status = client.get("/api/v1/sensors/status")
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not reach the backend: {exc}", _T)
        return

    st.markdown(
        '<div class="m5-page-header">'
        '<div class="m5-page-eyebrow">M5 · Operational Anomaly</div>'
        '<h1>Operational Anomaly Monitoring</h1>'
        '<p>Unsupervised anomaly detection over simulated methane, CO and airflow telemetry.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="m5-notice"><span class="m5-badge">SIMULATED TELEMETRY</span>'
        '<div class="m5-notice-copy"><strong>Telemetry Source</strong>'
        f'<span>{escape(str(status["notice"]))}</span></div></div>',
        unsafe_allow_html=True,
    )
    st.caption(status["separation_note"])

    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    with st.container(border=True):
        st.markdown(
            '<div class="m5-control-heading"><h2>Monitoring Controls</h2>'
            '<p>Select a mine, then choose a telemetry simulation mode.</p></div>',
            unsafe_allow_html=True,
        )
        mine_col, normal_col, anomaly_col = st.columns([1.35, 1, 1], gap="medium", vertical_alignment="bottom")
        with mine_col:
            chosen = st.selectbox("Mine", list(mine_names), key="anomaly_mine")
        mine_id = mine_names[chosen]
        with normal_col:
            simulate_normal = st.button(
                "Simulate NORMAL telemetry", key="m5_simulate_normal", use_container_width=True,
            )
        with anomaly_col:
            simulate_anomaly = st.button(
                "Simulate ANOMALOUS telemetry", key="m5_simulate_anomalous", use_container_width=True,
            )
        st.caption(
            "Demo-only generator, not a physical sensor feed - see services/telemetry_simulator.py. "
            "Uses the same generator shapes the Isolation Forest was trained to recognise."
        )

        if simulate_normal:
            try:
                client.post("/api/v1/sensors/simulate", params={"mine_id": mine_id, "mode": "normal"})
                st.success("Three SIMULATED normal-range readings recorded.")
            except ApiError as exc:
                error_state(f"Simulation failed: {exc}", _T)

        if simulate_anomaly:
            try:
                client.post("/api/v1/sensors/simulate", params={"mine_id": mine_id, "mode": "anomaly"})
                st.success("Three SIMULATED anomalous-combination readings recorded.")
            except ApiError as exc:
                error_state(f"Simulation failed: {exc}", _T)

    try:
        readings = client.get("/api/v1/sensors/readings", mine_id=mine_id, limit=20)
    except ApiError as exc:
        error_state(f"Could not load readings: {exc}", _T)
        return

    import altair as alt
    import pandas as pd

    detection_result = None
    detection_unavailable = None

    st.markdown(
        '<div class="m5-section"><h2>Live Telemetry Snapshot</h2>'
        '<p>Most recent recorded value for each monitored signal.</p></div>',
        unsafe_allow_html=True,
    )
    sensor_order = ["AIRFLOW", "CARBON_MONOXIDE", "METHANE"]
    sensor_labels = {
        "AIRFLOW": "AIRFLOW",
        "CARBON_MONOXIDE": "CARBON MONOXIDE",
        "METHANE": "METHANE",
    }
    sensor_colors = {
        "AIRFLOW": _T["ACCENT"],
        "CARBON_MONOXIDE": "#287C78",
        "METHANE": "#55758C",
    }
    latest_by_sensor = {}
    for reading in readings:
        latest_by_sensor.setdefault(reading["sensor_kind"], reading)

    snapshot_cards = []
    for sensor_kind in sensor_order:
        reading = latest_by_sensor.get(sensor_kind)
        value = escape(str(reading["value"])) if reading else "No reading"
        recorded_at = escape(str(reading["recorded_at"])) if reading else "No record available"
        snapshot_cards.append(
            f'<article class="m5-sensor-card" style="--m5-sensor:{sensor_colors[sensor_kind]}">'
            f'<span class="m5-sensor-label">{sensor_labels[sensor_kind]}</span>'
            f'<strong class="m5-sensor-value">{value}</strong>'
            f'<div class="m5-sensor-meta"><span>Recorded at {recorded_at}</span>'
            '<span class="m5-simulated-tag">SIMULATED</span></div></article>'
        )
    st.markdown(
        f'<div class="m5-snapshot-grid">{"".join(snapshot_cards)}</div>',
        unsafe_allow_html=True,
    )

    with st.container():
        run_detection = st.button(
            "Run M5 Isolation Forest detection", key="m5_run_detection",
            use_container_width=True,
        )
        if run_detection:
            try:
                result = client.post("/api/v1/sensors/detect", params={"mine_id": mine_id})
            except ApiError as exc:
                detection_unavailable = str(exc)
            else:
                if result.get("implemented") is False:
                    st.info(result["detail"])
                else:
                    detection_result = result

        try:
            anomaly_hist = client.get(f"/api/v1/sensors/mines/{mine_id}/anomaly-history")
            ordered_anomaly_history = sorted(anomaly_hist, key=lambda item: item["scored_at"])
        except ApiError:
            ordered_anomaly_history = []

        if detection_result is not None:
            latest_is_anomaly = detection_result["is_anomaly"]
            latest_anomaly_score = detection_result["anomaly_score"]
        elif ordered_anomaly_history:
            latest_detection = ordered_anomaly_history[-1]
            latest_is_anomaly = latest_detection["is_anomaly"]
            latest_anomaly_score = latest_detection["anomaly_score"]
        else:
            latest_is_anomaly = None
            latest_anomaly_score = None

        if latest_is_anomaly is None:
            status_label = "NO DETECTION RUN"
            status_detail = "Run M5 Isolation Forest detection to evaluate the latest telemetry."
            status_color = _T["TEXT_MUTED"]
        elif latest_is_anomaly:
            status_label = "ANOMALY DETECTED"
            status_detail = "Operational telemetry pattern requires attention."
            status_color = _T["RISK"]["CRITICAL"]
        else:
            status_label = "NORMAL"
            status_detail = "No operational anomaly detected."
            status_color = _T["RISK"]["LOW"]

        st.markdown(
            '<div class="m5-detection-panel" style="--m5-status:' + status_color + '">'
            '<div class="m5-detection-title">Anomaly Detection Status</div>'
            f'<div class="m5-detection-state">{escape(status_label)}</div>'
            f'<div class="m5-detection-detail">{escape(status_detail)}</div>'
            + (f'<div class="m5-detection-detail">M5 anomaly score (decision function): {escape(str(latest_anomaly_score))}</div>'
               if latest_anomaly_score is not None else "")
            + '</div>',
            unsafe_allow_html=True,
        )
        if detection_unavailable:
            st.warning(f"Detection unavailable: {detection_unavailable}")

    if detection_result is not None:
        st.caption(detection_result["separation_note"])
        if detection_result.get("capa_id"):
            st.success(f"CAPA raised: {detection_result['capa_id']}")

    st.markdown(
        '<div class="m5-section"><h2>Telemetry Trends</h2>'
        '<p>Recorded sensor values only. M5 anomaly scores are shown separately below.</p></div>',
        unsafe_allow_html=True,
    )
    if readings:
        chart_columns = st.columns(3, gap="medium")
        for chart_col, sensor_kind in zip(chart_columns, sensor_order):
            sensor_readings = [r for r in readings if r["sensor_kind"] == sensor_kind]
            with chart_col.container(border=True):
                latest_reading = latest_by_sensor.get(sensor_kind)
                latest_text = str(latest_reading["value"]) if latest_reading else "No reading"
                st.markdown(
                    '<div class="m5-chart-heading">'
                    f'<strong>{sensor_labels[sensor_kind]}</strong>'
                    f'<span class="m5-chart-current">{escape(latest_text)} · SIMULATED</span></div>',
                    unsafe_allow_html=True,
                )
                if sensor_readings:
                    ordered_readings = sorted(sensor_readings, key=lambda item: item["recorded_at"])
                    sensor_frame = pd.DataFrame([
                        {
                            "Recorded at": pd.to_datetime(reading["recorded_at"], utc=True),
                            "Recorded timestamp": reading["recorded_at"],
                            "Value": reading["value"],
                            "Unit": reading["unit"],
                            "Provenance": reading["provenance"],
                        }
                        for reading in ordered_readings
                    ])
                    sensor_chart = alt.Chart(sensor_frame).mark_line(
                        color=sensor_colors[sensor_kind], strokeWidth=2.4,
                        point=alt.OverlayMarkDef(filled=True, size=50, color=sensor_colors[sensor_kind]),
                    ).encode(
                        x=alt.X(
                            "Recorded at:T", title=None,
                            axis=alt.Axis(format="%H:%M", labelAngle=-25, labelOverlap="greedy", tickCount=4, grid=False),
                        ),
                        y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=True), axis=alt.Axis(tickCount=4, grid=True)),
                        tooltip=[
                            alt.Tooltip("Recorded timestamp:N", title="Recorded at"),
                            alt.Tooltip("Value:Q", title="Value"),
                            alt.Tooltip("Unit:N", title="Unit"),
                            alt.Tooltip("Provenance:N", title="Provenance"),
                        ],
                    ).properties(height=150).configure(
                        background=_T["SURFACE"],
                    ).configure_view(
                        strokeWidth=0,
                    ).configure_axis(
                        labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                        gridColor=_T["BORDER"], domainColor=_T["BORDER"],
                        labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=10,
                    )
                    st.altair_chart(sensor_chart, use_container_width=True)
                else:
                    st.caption("No reading recorded for this signal yet.")
    else:
        empty_state("No readings recorded for this mine yet.", _T)

    st.markdown(
        '<div class="m5-section"><h2>Recent Telemetry Records</h2>'
        '<p>Latest backend records, with original values, timestamps and provenance.</p></div>',
        unsafe_allow_html=True,
    )
    if readings:
        record_rows = "".join(
            '<tr>'
            f'<td>{escape(str(reading["sensor_kind"]))}</td>'
            f'<td>{escape(str(reading["value"]))} {escape(str(reading["unit"]))}</td>'
            f'<td>{escape(str(reading["recorded_at"]))}</td>'
            f'<td><span class="m5-provenance">{escape(str(reading["provenance"]))}</span></td>'
            '</tr>'
            for reading in readings
        )
        st.markdown(
            '<div class="m5-records-wrap"><table class="m5-records-table">'
            '<thead><tr><th>Sensor</th><th>Value</th><th>Recorded</th><th>Provenance</th></tr></thead>'
            f'<tbody>{record_rows}</tbody></table></div>',
            unsafe_allow_html=True,
        )
    else:
        empty_state("No telemetry records are available for this mine yet.", _T)

    st.markdown(
        '<div class="m5-section"><h2>M5 Anomaly Score History</h2>'
        '<p>Historical anomaly scores for the selected mine. This metric is independent from the M3 operational risk score.</p></div>',
        unsafe_allow_html=True,
    )
    if ordered_anomaly_history:
        history_frame = pd.DataFrame([
            {
                "Scored at": pd.to_datetime(item["scored_at"], utc=True),
                "Recorded timestamp": item["scored_at"],
                "M5 anomaly score": item["anomaly_score"],
                "Anomalous": item["is_anomaly"],
                "Provenance": item["provenance"],
            }
            for item in ordered_anomaly_history
        ])
        history_chart = alt.Chart(history_frame).mark_line(
            color=_T["ACCENT"], strokeWidth=2.4,
            point=alt.OverlayMarkDef(filled=True, size=58, color=_T["ACCENT"]),
        ).encode(
            x=alt.X(
                "Scored at:T", title="Scored at", sort="ascending",
                axis=alt.Axis(format="%d %b %H:%M", labelAngle=-25, labelOverlap="greedy", tickCount=6, grid=False),
            ),
            y=alt.Y(
                "M5 anomaly score:Q",
                title="M5 anomaly score (Isolation Forest decision function)",
                axis=alt.Axis(tickCount=5, grid=True),
            ),
            tooltip=[
                alt.Tooltip("Recorded timestamp:N", title="Recorded at"),
                alt.Tooltip("M5 anomaly score:Q", title="M5 anomaly score"),
                alt.Tooltip("Anomalous:N", title="Anomalous"),
                alt.Tooltip("Provenance:N", title="Provenance"),
            ],
        ).properties(height=250).configure(
            background=_T["SURFACE"],
        ).configure_view(
            strokeWidth=0,
        ).configure_axis(
            labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
            gridColor=_T["BORDER"], domainColor=_T["BORDER"],
            labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=10,
        )
        with st.container(border=True):
            st.altair_chart(history_chart, use_container_width=True)
    else:
        empty_state(
            "No anomaly detection has been run yet for this mine. "
            "Run the M5 Isolation Forest detection to generate anomaly results.",
            _T,
        )

    st.markdown(
        '<div class="m5-howto"><h3>How to read M5</h3>'
        '<ol><li>Select a mine.</li><li>Review the simulated environmental telemetry.</li>'
        '<li>Run M5 Isolation Forest detection.</li><li>Review whether the current telemetry pattern is anomalous.</li>'
        '<li>Inspect the anomaly score history.</li></ol>'
        '<div class="m5-howto-warning">M5 anomaly detection is an operational telemetry signal. '
        'It is not an accident probability and must not be interpreted as M3 risk.</div></div>',
        unsafe_allow_html=True,
    )


def render_capa(client: ApiClient, user: dict):
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    selected_context = st.session_state.get("capa_mine")
    if selected_context not in mine_names:
        selected_context = next(iter(mine_names))
    st.markdown(
        '<div class="m4-header"><div class="m4-eyebrow">M4 · CAPA &amp; Escalation</div>'
        '<h1>Corrective Action Management</h1>'
        '<p>Corrective Action &amp; Preventive Action Management</p>'
        f'<span class="m4-context-note">Current mine · {escape(str(selected_context))}</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown('<div class="m4-context-label">MINE CONTEXT</div>', unsafe_allow_html=True)
        chosen = st.selectbox("Mine", list(mine_names), key="capa_mine")
        st.markdown(
            f'<span class="m4-context-name">{escape(str(chosen))}</span>'
            '<span class="m4-context-note">Current CAPA activity for selected mine</span>',
            unsafe_allow_html=True,
        )
    mine_id = mine_names[chosen]

    try:
        items = client.get("/api/v1/capa", mine_id=mine_id)
    except ApiError as exc:
        error_state(str(exc), _T)
        return

    from collections import Counter
    status_colors = {
        "OPEN": _T["RISK"]["MEDIUM"],
        "ASSIGNED": _T["ACCENT"],
        "IN_PROGRESS": _T["ACCENT"],
        "EVIDENCE_SUBMITTED": "#287C78",
        "VERIFIED": _T["RISK"]["LOW"],
        "CLOSED": "#37634C",
    }
    status_counts = Counter(i["status"] for i in items)
    closed_count = status_counts.get("CLOSED", 0)
    completion_pct = (closed_count / len(items) * 100) if items else 0

    st.markdown(
        '<div class="m4-section"><h2>CAPA workload</h2>'
        '<p>Current status counts for this mine, based on its returned CAPA records.</p></div>',
        unsafe_allow_html=True,
    )
    metric_specs = [
        ("TOTAL CAPA", len(items), _T["ACCENT"]),
        ("OPEN", status_counts.get("OPEN", 0), status_colors["OPEN"]),
        ("IN PROGRESS", status_counts.get("IN_PROGRESS", 0), status_colors["IN_PROGRESS"]),
        ("CLOSED", closed_count, status_colors["CLOSED"]),
    ]
    metric_html = "".join(
        '<div class="m4-metric" style="--m4-tone:' + color + '">'
        f'<span class="m4-metric-label">{escape(label)}</span>'
        f'<strong class="m4-metric-value">{count}</strong></div>'
        for label, count, color in metric_specs
    )
    st.markdown(f'<div class="m4-metrics">{metric_html}</div>', unsafe_allow_html=True)

    chart_col, completion_col = st.columns([1.35, 1], gap="medium")
    with chart_col:
        st.markdown(
            '<div class="m4-section"><h2>Status distribution</h2>'
            '<p>CAPA workload by current workflow status.</p></div>',
            unsafe_allow_html=True,
        )
        if status_counts:
            import altair as alt
            import pandas as pd

            statuses = list(status_counts)
            status_chart_data = pd.DataFrame([
                {
                    "Status": status.replace("_", " "),
                    "Status code": status,
                    "Items": count,
                }
                for status, count in status_counts.items()
            ])
            chart = alt.Chart(status_chart_data).mark_bar(
                cornerRadiusEnd=3, size=19,
            ).encode(
                x=alt.X("Items:Q", title="CAPA items", scale=alt.Scale(domainMin=0), axis=alt.Axis(tickMinStep=1, grid=True)),
                y=alt.Y("Status:N", title=None, sort=alt.SortField(field="Items", order="descending"),
                        axis=alt.Axis(ticks=False, domain=False)),
                color=alt.Color(
                    "Status code:N", scale=alt.Scale(
                        domain=statuses, range=[status_colors.get(status, _T["ACCENT"]) for status in statuses],
                    ), legend=None,
                ),
                tooltip=[
                    alt.Tooltip("Status:N", title="Status"),
                    alt.Tooltip("Items:Q", title="CAPA items"),
                ],
            ).properties(
                height=max(105, min(230, len(status_counts) * 38)),
            ).configure(
                background=_T["SURFACE"],
            ).configure_view(
                strokeWidth=0,
            ).configure_axis(
                labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                gridColor=_T["BORDER"], domainColor=_T["BORDER"],
                labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=11,
            )
            with st.container(border=True):
                st.altair_chart(chart, use_container_width=True)
        else:
            empty_state("No CAPA status data is available for this mine.", _T)

    with completion_col:
        st.markdown(
            '<div class="m4-section"><h2>CAPA completion</h2>'
            '<p>Closed items out of the selected mine\'s total CAPA workload.</p></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="m4-completion"><div class="m4-completion-label">CAPA COMPLETION</div>'
            f'<div class="m4-completion-main"><strong>{closed_count} / {len(items)}</strong><span>Closed</span></div>'
            f'<div class="m4-progress-track"><div class="m4-progress-fill" style="width:{completion_pct:.4f}%"></div></div>'
            f'<span class="m4-progress-caption">{completion_pct:.1f}% completed</span></div>'
            f'<span class="m4-chart-caption">{closed_count} of {len(items)} CAPA item(s) for this mine are CLOSED.</span>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="m4-section"><h2>CAPA items</h2>'
        '<p>Review existing corrective actions and update their workflow status.</p></div>',
        unsafe_allow_html=True,
    )
    if not items:
        empty_state("No CAPA items for this mine.", _T)

    for item in items:
        badge = severity_badge(item["severity"], _T)
        status_badge = severity_badge(item["status"], _T)
        severity = escape(str(item.get("severity") or "Not specified"))
        source_type = escape(str(item.get("source_type") or "Not specified"))
        status_value = escape(str(item.get("status") or "Not specified"))
        description = item.get("description") or "No data available"
        due_date = item.get("due_date") or "Not specified"
        escalation_level = item.get("escalation_level")
        if escalation_level is None:
            escalation_level = "Not specified"
        metadata = [
            ("CAPA ID", item.get("id")),
            ("Mine", chosen),
            ("Mine ID", mine_id),
            ("Source", item.get("source_type")),
            ("Severity", item.get("severity")),
            ("Status", item.get("status")),
            ("Due date", due_date),
            ("Escalation level", escalation_level),
        ]
        metadata_html = "".join(
            '<div class="m4-meta-cell">'
            f'<span class="m4-meta-label">{escape(str(label))}</span>'
            f'<span class="m4-meta-value">{escape(str(value)) if value not in (None, "") else "Not specified"}</span>'
            '</div>'
            for label, value in metadata
        )
        with st.container(border=True):
            st.markdown(
                '<div class="m4-item-heading">'
                f'<span class="m4-item-type">{source_type}</span>{badge}{status_badge}</div>'
                f'<div class="m4-meta-grid">{metadata_html}</div>'
                '<div class="m4-meta-label" style="margin-top:10px">DESCRIPTION</div>'
                f'<div class="m4-description">{escape(str(description))}</div>',
                unsafe_allow_html=True,
            )
            with st.expander("View raw CAPA data"):
                st.json(item)

            st.markdown(
                '<div class="m4-transition-label">UPDATE CAPA STATUS</div>'
                '<div class="m4-transition-note">Update the CAPA workflow status and record the operational justification.</div>',
                unsafe_allow_html=True,
            )
            current_col, target_col = st.columns([1, 2], gap="medium")
            with current_col:
                st.markdown('<div class="m4-meta-label">CURRENT STATUS</div>', unsafe_allow_html=True)
                st.markdown(status_badge, unsafe_allow_html=True)
            with target_col:
                new_status = st.selectbox(
                    "Move to", ["ASSIGNED", "IN_PROGRESS", "EVIDENCE_SUBMITTED", "VERIFIED", "CLOSED"],
                    key=f"transition_{item['id']}",
                )
            note = st.text_area("Justification", key=f"note_{item['id']}", height=72)
            if st.button("Apply Transition", key=f"btn_{item['id']}"):
                try:
                    client.post(f"/api/v1/capa/{item['id']}/transition",
                               {"to_status": new_status, "note": note or None})
                    st.success("Transition applied.")
                    st.rerun()
                except ApiError as exc:
                    error_state(f"Transition rejected by the backend: {exc}", _T)


def render_documents(client: ApiClient):
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    st.markdown(
        '<div class="m1-header"><div class="m1-eyebrow">M1 · Document Intelligence</div>'
        '<h1>Document Intelligence &amp; Verification</h1>'
        '<p>Upload, extract and verify statutory mine documents.</p>'
        '<span class="page-context-badge">DOCUMENT CONTROL</span></div>',
        unsafe_allow_html=True,
    )
    chosen = st.selectbox("Mine", list(mine_names), key="doc_mine")
    mine_id = mine_names[chosen]

    with st.container(border=True):
        st.markdown('<div class="m1-section"><h2>SELECTED MINE</h2></div>', unsafe_allow_html=True)
        st.markdown(f'<strong class="map-detail-value">{escape(chosen)}</strong>', unsafe_allow_html=True)

    st.markdown(
        '<div class="m1-section"><h2>DOCUMENT WORKFLOW</h2>'
        '<p>Conceptual process only; completion states are shown from each document record below.</p></div>',
        unsafe_allow_html=True,
    )
    workflow_html = "".join(
        f'<div class="m1-step"><span class="m1-eyebrow">0{index}</span><br>{label}</div>'
        for index, label in enumerate(["UPLOAD", "OCR EXTRACTION", "REVIEW", "VERIFICATION", "COMPLIANCE"], 1)
    )
    st.markdown(f'<div class="m1-workflow">{workflow_html}</div>', unsafe_allow_html=True)

    upload_col, ocr_col = st.columns(2, gap="medium")
    with upload_col:
        with st.container(border=True):
            st.markdown(
                '<div class="m1-section"><h2>UPLOAD DOCUMENT</h2>'
                '<p>Add a statutory document record for this mine.</p></div>',
                unsafe_allow_html=True,
            )
            with st.expander("Upload a new document"):
                doc_type = st.text_input("Document type", value="Safety Certificate")
                if st.button("Create document record"):
                    try:
                        doc = client.post("/api/v1/documents", {"mine_id": mine_id, "doc_type": doc_type})
                        st.success(f"Document created: {doc['id']}")
                        st.session_state["last_doc_id"] = doc["id"]
                    except ApiError as exc:
                        error_state(f"Could not create document: {exc}", _T)

    with ocr_col:
        with st.container(border=True):
            st.markdown(
                '<div class="m1-section"><h2>OCR EXTRACTION</h2>'
                '<p>Extract structured information from the uploaded document.</p></div>',
                unsafe_allow_html=True,
            )
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
    pending_count = sum(1 for doc in docs if doc.get("verification_status") == "PENDING_VERIFICATION")
    verified_count = sum(1 for doc in docs if doc.get("verification_status") == "VERIFIED")
    processed_count = sum(1 for doc in docs if doc.get("ocr_engine") is not None)
    doc_metrics = [
        ("DOCUMENTS", len(docs), _T["ACCENT"]),
        ("PENDING VERIFICATION", pending_count, _T["RISK"]["MEDIUM"] if pending_count else _T["RISK"]["LOW"]),
        ("OCR PROCESSED", processed_count, _T["ACCENT"]),
        ("VERIFIED", verified_count, _T["RISK"]["LOW"]),
    ]
    doc_metric_html = "".join(
        f'<div class="m1-metric" style="--metric-tone:{tone}">'
        f'<span class="m1-metric-label">{label}</span><strong class="m1-metric-value">{count}</strong></div>'
        for label, count, tone in doc_metrics
    )
    st.markdown(f'<div class="m1-summary">{doc_metric_html}</div>', unsafe_allow_html=True)

    if pending_count:
        st.markdown(
            '<div class="m0-action"><strong>HUMAN VERIFICATION REQUIRED</strong><br>'
            'Extracted information must be reviewed before being treated as verified compliance.</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="m1-section"><h2>DOCUMENT REGISTER</h2>'
        '<p>Document metadata and processing state returned for the selected mine.</p></div>',
        unsafe_allow_html=True,
    )
    if docs:
        doc_cards = []
        for doc in docs:
            confidence = doc.get("ocr_confidence")
            verification = str(doc["verification_status"])
            verification_color = _T["RISK"]["LOW"] if verification == "VERIFIED" else _T["RISK"]["MEDIUM"] if verification == "PENDING_VERIFICATION" else _T["TEXT_MUTED"]
            doc_cards.append(
                '<div class="m1-card">'
                f'<div class="m1-eyebrow">{escape(str(doc["doc_type"]))}</div>'
                '<div class="map-detail-grid" style="margin-top:8px">'
                f'<div><span class="map-detail-label">OCR ENGINE</span><strong>{escape(str(doc.get("ocr_engine") or "None"))}</strong></div>'
                f'<div><span class="map-detail-label">OCR CONFIDENCE</span><strong>{escape(str(confidence) if confidence is not None else "Not available")}</strong></div>'
                '</div>'
                f'<div class="map-note" style="border-left-color:{verification_color}">VERIFICATION · {escape(verification)}</div>'
                '</div>'
            )
        st.markdown(f'<div class="m1-document-grid">{"".join(doc_cards)}</div>', unsafe_allow_html=True)
    else:
        empty_state("NO DOCUMENTS FOR THIS MINE. Upload a statutory document to begin the document intelligence workflow.", _T)


def render_compliance(client: ApiClient):
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    st.markdown(
        '<div class="m0-header"><div class="m0-eyebrow">M0 · Statutory Compliance</div>'
        '<h1>Statutory Compliance</h1>'
        '<p>Monitor mine-level statutory obligations, evidence status and upcoming compliance actions.</p>'
        '<span class="page-context-badge">COMPLIANCE CONTROL</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown('<span class="m0-eyebrow">SELECTED MINE</span>', unsafe_allow_html=True)
        chosen = st.selectbox("Mine", list(mine_names), key="compliance_mine")
        st.markdown(f'<strong class="map-detail-value">{escape(chosen)}</strong>', unsafe_allow_html=True)
    mine_id = mine_names[chosen]

    try:
        obligations = client.get(f"/api/v1/mines/{mine_id}/obligations")
    except ApiError as exc:
        error_state(f"Could not load obligations: {exc}", _T)
        return
    from collections import Counter
    status_counts = Counter(o["status"] for o in obligations)

    missing_count = status_counts.get("MISSING", 0)
    due_count = status_counts.get("DUE", 0)
    overdue_count = status_counts.get("OVERDUE", 0)
    satisfied_count = status_counts.get("SATISFIED", 0)
    due_attention = due_count + overdue_count
    m0_metrics = [
        ("TOTAL OBLIGATIONS", len(obligations), _T["ACCENT"]),
        ("MISSING", missing_count, _T["RISK"]["MEDIUM"] if missing_count else _T["RISK"]["LOW"]),
        ("DUE / OVERDUE", due_attention, _T["RISK"]["CRITICAL"] if overdue_count else _T["RISK"]["MEDIUM"] if due_count else _T["RISK"]["LOW"]),
        ("SATISFIED", satisfied_count, _T["RISK"]["LOW"]),
    ]
    m0_metric_html = "".join(
        f'<div class="m0-metric" style="--metric-tone:{tone}">'
        f'<span class="m0-metric-label">{label}</span><strong class="m0-metric-value">{value}</strong></div>'
        for label, value, tone in m0_metrics
    )
    st.markdown(f'<div class="m0-summary">{m0_metric_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="m0-section"><h2>Compliance status</h2>'
        '<p>Counts reflect only the selected mine’s returned obligation records; no compliance percentage is inferred.</p></div>',
        unsafe_allow_html=True,
    )
    status_colors = {
        "MISSING": _T["RISK"]["MEDIUM"], "DUE": _T["RISK"]["MEDIUM"],
        "OVERDUE": _T["RISK"]["CRITICAL"], "SATISFIED": _T["RISK"]["LOW"],
    }
    status_strip = "".join(
        f'<span class="m0-status-pill" style="color:{status_colors.get(status, _T["ACCENT"])}">'
        f'<strong>{escape(status.replace("_", " "))}</strong> · {count}</span>'
        for status, count in status_counts.items()
    )
    st.markdown(f'<div class="m0-health"><div class="m0-status-list">{status_strip or "No status data available"}</div></div>', unsafe_allow_html=True)

    chart_col, action_col = st.columns([1.4, 1], gap="medium")
    with chart_col:
        st.markdown(
            '<div class="m0-section"><h2>Obligation status distribution</h2>'
            '<p>Current obligation status for the selected mine.</p></div>',
            unsafe_allow_html=True,
        )
        if status_counts:
            import altair as alt
            import pandas as pd

            statuses = list(status_counts)
            chart_data = pd.DataFrame([
                {"Status": status.replace("_", " "), "Status code": status, "Obligations": count}
                for status, count in status_counts.items()
            ])
            chart = alt.Chart(chart_data).mark_bar(cornerRadiusEnd=3, size=18).encode(
                x=alt.X("Obligations:Q", title="Obligations", scale=alt.Scale(domainMin=0), axis=alt.Axis(tickMinStep=1)),
                y=alt.Y("Status:N", title=None, sort=alt.SortField(field="Obligations", order="descending"), axis=alt.Axis(ticks=False, domain=False)),
                color=alt.Color("Status code:N", scale=alt.Scale(
                    domain=statuses, range=[status_colors.get(status, _T["ACCENT"]) for status in statuses],
                ), legend=None),
                tooltip=[alt.Tooltip("Status:N"), alt.Tooltip("Obligations:Q")],
            ).properties(height=max(100, min(210, 38 * len(status_counts)))).configure(
                background=_T["SURFACE"],
            ).configure_view(strokeWidth=0).configure_axis(
                labelColor=_T["TEXT_MUTED"], titleColor=_T["TEXT"],
                gridColor=_T["BORDER"], domainColor=_T["BORDER"],
                labelFont=FONT_UI, titleFont=FONT_UI, labelFontSize=11,
            )
            with st.container(border=True):
                st.altair_chart(chart, use_container_width=True)
        else:
            empty_state("No obligation status data is available for this mine.", _T)

    with action_col:
        if missing_count:
            st.markdown(
                '<div class="m0-action"><strong>ACTION REQUIRED</strong><br>'
                'One or more statutory obligations for this mine currently show MISSING status.'
                '<br><span class="m4-chart-caption">No evidence has ever been supplied for these applicable rules.</span></div>',
                unsafe_allow_html=True,
            )
        elif not obligations:
            empty_state("No obligations recorded for this mine.", _T)
        else:
            st.markdown(
                '<div class="m0-health"><strong>No MISSING obligations</strong><br>'
                '<span class="m4-chart-caption">Current statuses are shown in the obligation register.</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        '<div class="m0-section"><h2>Obligation register</h2>'
        '<p>Status and recorded due/satisfaction dates from the current obligation data.</p></div>',
        unsafe_allow_html=True,
    )
    if obligations:
        obligation_rows = "".join(
            '<tr>'
            f'<td><span class="m0-status-pill" style="color:{status_colors.get(o["status"], _T["ACCENT"])}">{escape(str(o["status"]).replace("_", " "))}</span></td>'
            f'<td>{escape(str(o.get("next_due_date") or "Not specified"))}</td>'
            f'<td>{escape(str(o.get("last_satisfied_date") or "Not specified"))}</td>'
            '</tr>'
            for o in obligations
        )
        st.markdown(
            '<div class="m5-records-wrap"><table class="m5-records-table">'
            '<thead><tr><th>STATUS</th><th>NEXT DUE</th><th>LAST SATISFIED</th></tr></thead>'
            f'<tbody>{obligation_rows}</tbody></table></div>',
            unsafe_allow_html=True,
        )
    else:
        empty_state("No obligations recorded for this mine.", _T)


def render_voice(client: ApiClient):
    st.markdown(
        '<div class="voice-header"><div class="voice-eyebrow">Voice Incident Reporting</div>'
        '<h1>Voice Incident Command Center</h1>'
        '<p>Capture mine incidents through voice and route them through transcription, translation, incident handling, CAPA and audit.</p></div>',
        unsafe_allow_html=True,
    )
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    workflow = ["AUDIO", "ASR", "TRANSCRIPT", "TRANSLATION", "INCIDENT", "CAPA", "AUDIT"]
    workflow_html = "".join(
        f'<div class="voice-step"><span class="voice-eyebrow">0{index}</span><br>{label}</div>'
        for index, label in enumerate(workflow, 1)
    )
    st.markdown(f'<div class="voice-workflow">{workflow_html}</div>', unsafe_allow_html=True)

    context_col, info_col = st.columns([1.6, 1], gap="medium")
    with context_col:
        with st.container(border=True):
            st.markdown(
                '<div class="voice-section"><h2>CAPTURE A VOICE INCIDENT</h2>'
                '<p>Record incident context and upload the voice evidence.</p></div>',
                unsafe_allow_html=True,
            )
            mine_col, category_col = st.columns(2, gap="medium")
            with mine_col:
                chosen = st.selectbox("Mine", list(mine_names), key="voice_mine")
            mine_id = mine_names[chosen]
            with category_col:
                category = st.text_input("Category", value="Ventilation concern")
            severity_col, language_col = st.columns(2, gap="medium")
            with severity_col:
                severity = st.selectbox("Severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
            with language_col:
                language = st.selectbox("Source language", ["hi", "bn", "te", "or", "en"])
            st.markdown('<div class="voice-section"><h2>AUDIO EVIDENCE</h2><p>Upload the voice recording containing the incident report. Accepted formats: WAV, MP3, M4A, OGG.</p></div>', unsafe_allow_html=True)
            audio = st.file_uploader("Upload audio", type=["wav", "mp3", "m4a", "ogg"])
            st.caption("Audio is submitted as evidence through the existing incident workflow.")

            if st.button("Submit voice incident", type="primary", use_container_width=True) and audio:
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

                st.markdown('<div class="voice-section"><h2>INCIDENT PROCESSING STATUS</h2></div>', unsafe_allow_html=True)
                transcript_col, translation_col = st.columns(2, gap="medium")
                with transcript_col:
                    with st.container(border=True):
                        st.markdown('<div class="voice-eyebrow">ORIGINAL TRANSCRIPT</div>', unsafe_allow_html=True)
                        st.text_area("Original transcript", result.get("original_transcript") or "(none)")
                with translation_col:
                    with st.container(border=True):
                        st.markdown('<div class="voice-eyebrow">ENGLISH TRANSLATION</div>', unsafe_allow_html=True)
                        st.text_area("English translation", result.get("translated_transcript") or "(none)")
                if result.get("capa_id"):
                    st.markdown(
                        '<div class="voice-card"><strong>CAPA CREATED</strong><br>'
                        f'<span class="anthryx-id">{escape(str(result["capa_id"]))}</span>'
                        '<br><span class="m4-chart-caption">Track this corrective action in M4 CAPA.</span></div>',
                        unsafe_allow_html=True,
                    )
    with info_col:
        with st.container(border=True):
            st.markdown(
                '<div class="voice-section"><h2>VOICE PROCESSING</h2>'
                '<p>Existing processing path</p></div>'
                '<div class="voice-card">Audio → Bhashini ASR → Original transcript → Bhashini NMT → English translation</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="voice-note"><strong>READY TO CAPTURE</strong><br>'
                'Incident processing results appear after a voice submission. Provider and fallback status are displayed from the returned response.</div>',
                unsafe_allow_html=True,
            )


def render_audit(client: ApiClient):
    st.markdown(
        '<div class="audit-header"><div class="audit-eyebrow">Audit &amp; Integrity Center</div>'
        '<h1>Audit Ledger</h1><p>Tamper-evident operational audit trail.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="audit-note"><strong>LEDGER INTEGRITY</strong><br>'
        'Tamper-evident hash chain. Not immutable. Not a blockchain.</div>',
        unsafe_allow_html=True,
    )
    try:
        entries = client.get("/api/v1/audit", limit=100)
    except ApiError as exc:
        error_state(f"Could not load audit entries: {exc}", _T)
        return
    latest_entry = max(entries, key=lambda entry: entry["seq"]) if entries else None
    audit_metrics = [
        ("TOTAL EVENTS", len(entries), _T["ACCENT"]),
        ("LATEST SEQUENCE", latest_entry["seq"] if latest_entry else "—", _T["ACCENT"]),
        ("LATEST ACTIVITY", format_timestamp(latest_entry["timestamp"]) if latest_entry else "No events", _T["TEXT_MUTED"]),
    ]
    audit_metric_html = "".join(
        f'<div class="audit-metric" style="--metric-tone:{tone}">'
        f'<span class="audit-metric-label">{label}</span><strong class="audit-metric-value">{escape(str(value))}</strong></div>'
        for label, value, tone in audit_metrics
    )
    st.markdown(f'<div class="audit-summary">{audit_metric_html}</div>', unsafe_allow_html=True)
    st.markdown('<div class="audit-section"><h2>LEDGER EVENTS</h2><p>Latest events returned by the audit ledger.</p></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.dataframe(
            [{"seq": e["seq"], "timestamp": format_timestamp(e["timestamp"]),
              "actor": (e.get("actor_id") or "system")[:8], "action": e["action"],
              "entity": e["entity_type"], "entity_id": (e.get("entity_id") or "-")[:8],
              "hash": (e.get("row_hash") or "")[:12]} for e in entries],
            use_container_width=True, hide_index=True,
        )
    if st.button("Verify Ledger", type="secondary"):
        try:
            result = client.get("/api/v1/audit/verify")
        except ApiError as exc:
            error_state(f"Verification failed: {exc}", _T)
            return
        if result["intact"]:
            st.success(f"LEDGER VERIFIED · Chain intact - {result['entries_checked']} entries checked.")
        else:
            error_state(f"TAMPERING DETECTED at sequence {result['broken_at_seq']}.", _T)


def render_gis(client: ApiClient):
    st.markdown(
        '<div class="map-header"><div class="map-eyebrow">Mine Risk Intelligence</div>'
        '<h1>Mine Risk Map</h1>'
        '<p>Geospatial view of operational risk across monitored mining sites.</p>'
        '<span class="page-context-badge">LIVE OPERATIONAL VIEW</span></div>',
        unsafe_allow_html=True,
    )
    try:
        overview = client.get("/api/v1/mines/risk-overview")
    except ApiError as exc:
        error_state(f"Could not load mine risk overview: {exc}", _T)
        return

    risk_counts = {
        level: sum(1 for mine in overview if mine.get("risk_category") == level)
        for level in ("HIGH", "MEDIUM", "LOW")
    }
    no_score_count = sum(1 for mine in overview if mine.get("risk_score") is None)
    map_metrics = [
        ("TOTAL MINES", len(overview), _T["ACCENT"], "Monitored locations"),
        ("HIGH RISK", risk_counts["HIGH"], _T["RISK"]["HIGH"], "Requires attention"),
        ("MEDIUM RISK", risk_counts["MEDIUM"], _T["RISK"]["MEDIUM"], "Elevated operational risk"),
        ("LOW RISK", risk_counts["LOW"], _T["RISK"]["LOW"], "Lower current risk"),
        ("NO SCORE", no_score_count, _T["TEXT_MUTED"], "Not yet assessed"),
    ]
    map_metric_html = "".join(
        f'<div class="map-metric" style="--metric-tone:{tone}">'
        f'<span class="map-metric-label">{label}</span>'
        f'<strong class="map-metric-value">{count}</strong>'
        f'<span class="m4-chart-caption">{detail}</span></div>'
        for label, count, tone, detail in map_metrics
    )
    st.markdown(f'<div class="map-summary map-summary-five">{map_metric_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="map-note"><strong>MAP DATA NOTE</strong><br>'
        'Coordinates reflect the recorded mine locations; provenance below identifies approximate/demo records. '
        'The scatter risk view does not depend on external map tiles. '
        'Marker colour reflects M3 operational risk only; M5 anomaly state remains independent.</div>',
        unsafe_allow_html=True,
    )

    located = [m for m in overview if m.get("latitude") is not None and m.get("longitude") is not None]
    unlocated = [m for m in overview if m not in located]

    RISK_COLOR = {"HIGH": _T["RISK"]["HIGH"], "MEDIUM": _T["RISK"]["MEDIUM"],
                 "LOW": _T["RISK"]["LOW"], None: _T["TEXT_MUTED"]}

    if not located:
        empty_state("No mine in this dataset has coordinates recorded. Nothing is plotted rather than inventing a location.", _T)
    else:
        with st.container(border=True):
            st.markdown(
                '<div class="map-section"><h2>OPERATIONAL RISK MAP</h2>'
                '<p>Geographic distribution of monitored mine locations · M3 operational risk only</p></div>',
                unsafe_allow_html=True,
            )
            import pandas as pd
            df = pd.DataFrame([
                {"Mine": m["name"], "State": m.get("state") or "-",
                 "Longitude": m["longitude"], "Latitude": m["latitude"],
                 "Risk category": m["risk_category"] or "Not yet scored",
                 "Risk score": m["risk_score"] if m["risk_score"] is not None else 0.05,
                    "Latitude": m["latitude"],
                    "Longitude": m["longitude"],
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
                .mark_circle(opacity=0.86, stroke=_T["SURFACE"], strokeWidth=1.5)
                .encode(
                    x=alt.X("Longitude:Q", scale=alt.Scale(
                        domain=[df["Longitude"].min() - lon_pad, df["Longitude"].max() + lon_pad]),
                        title="Longitude"),
                    y=alt.Y("Latitude:Q", scale=alt.Scale(
                        domain=[df["Latitude"].min() - lat_pad, df["Latitude"].max() + lat_pad]),
                        title="Latitude"),
                    color=alt.Color("color:N", scale=None, legend=None),
                    size=alt.Size("Risk score:Q", scale=alt.Scale(range=[180, 620]), legend=None),
                    tooltip=["Mine", "State", "Risk category", "Risk score", "Latitude", "Longitude"],
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
            legend_html = "".join(
                f'<span><b style="color:{color}">●</b> {label}</span>'
                for label, color in [
                    ("HIGH", RISK_COLOR["HIGH"]), ("MEDIUM", RISK_COLOR["MEDIUM"]),
                    ("LOW", RISK_COLOR["LOW"]), ("NO SCORE", RISK_COLOR[None]),
                ]
            )
            st.markdown(
                '<div class="map-section"><span class="map-detail-label">RISK LEVEL</span>'
                f'<div class="map-legend">{legend_html}</div>'
                '<span class="m4-chart-caption">M3 operational risk only</span></div>',
                unsafe_allow_html=True,
            )

            with st.expander("GEOGRAPHIC BASEMAP · Optional geographic context", expanded=False):
                st.caption("Optional external map layer. The risk view remains available without external map access.")
                if st.button("Load geographic basemap", key="load_geographic_basemap"):
                    st.map([{"lat": m["latitude"], "lon": m["longitude"]} for m in located])

    if unlocated:
        st.markdown(
            f'<div class="map-note">{len(unlocated)} mine(s) have no coordinates and are not shown: '
            + escape(", ".join(m["name"] for m in unlocated)) + '</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="map-section"><span class="map-eyebrow">Selected Mine</span>'
        '<h2>Mine details</h2></div>',
        unsafe_allow_html=True,
    )
    if not overview:
        empty_state("No mines available.", _T)
        return
    names = {m["name"]: m for m in overview}
    chosen = st.selectbox("Select a mine to view details", list(names))
    m = names[chosen]

    category = m["risk_category"] or "No score"
    risk_tone = RISK_COLOR.get(m["risk_category"], _T["TEXT_MUTED"])
    score_display = m["risk_score"] if m["risk_score"] is not None else "Not yet scored"
    details = [
        ("M3 OPERATIONAL RISK", score_display, risk_tone),
        ("RISK CATEGORY", category, risk_tone),
        ("OPEN CAPA", m["open_capa_count"], _T["RISK"]["MEDIUM"] if m["open_capa_count"] else _T["RISK"]["LOW"]),
        ("OVERDUE CAPA", m["overdue_capa_count"], _T["RISK"]["CRITICAL"] if m["overdue_capa_count"] else _T["RISK"]["LOW"]),
        ("LAST INSPECTION", format_timestamp(m["last_inspection_at"]) if m["last_inspection_at"] else "Never inspected", _T["ACCENT"]),
    ]
    detail_html = "".join(
        f'<div class="map-card"><span class="map-detail-label">{label}</span>'
        f'<strong class="map-detail-value" style="color:{tone}">{escape(str(value))}</strong></div>'
        for label, value, tone in details
    )
    provenance = f'{m["coordinate_provenance"]} · {"APPROXIMATE" if m["coordinate_is_approximate"] else "SURVEYED"}'
    st.markdown(
        f'<span class="map-provenance">COORDINATE PROVENANCE · {escape(provenance)}</span>'
        f'<div class="map-detail-grid">{detail_html}</div>',
        unsafe_allow_html=True,
    )

    if m["rescore_required"]:
        st.warning("A CAPA closed since this score was computed - it may be stale. Rebuild features on the M3 Risk page.")

    st.markdown(
        f"M5 latest reading: {'ANOMALOUS' if m['m5_is_anomaly'] else 'normal/none run yet' if m['m5_is_anomaly'] is not None else 'no telemetry scored yet'}"
        + (f" (score {m['m5_anomaly_score']})" if m["m5_anomaly_score"] is not None else "")
        + " - SIMULATED, and never the same score as M3 risk.",
        unsafe_allow_html=False,
    )

    if m["explanation"]:
        st.markdown(
            '<div class="map-section"><h2>Major contributing factors</h2>'
            '<p>Real SHAP contributions for this mine.</p></div>',
            unsafe_allow_html=True,
        )
        rows = sorted(m["explanation"].items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
        max_contribution = max((abs(float(value)) for _, value in rows), default=0.0) or 1.0
        shap_html = "".join(
            '<div class="map-shap-row">'
            f'<span>{escape(str(feature))}</span>'
            '<span class="map-shap-track"><span class="map-shap-fill" '
            f'style="width:{abs(float(value))/max_contribution*50:.2f}%;'
            f'left:{(50.0 if value >= 0 else 50.0-abs(float(value))/max_contribution*50):.2f}%;'
            f'background:{_T["ACCENT"] if value >= 0 else _T["RISK"]["LOW"]}"></span></span>'
            f'<strong>{escape(str(value))}</strong></div>'
            for feature, value in rows
        )
        st.markdown(f'<div class="map-card map-shap-list">{shap_html}</div>', unsafe_allow_html=True)
    else:
        st.caption("No risk explanation available yet - build features and score this mine on the M3 Risk page.")

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
    try:
        overview = client.get("/api/v1/mines/risk-overview")
    except ApiError as exc:
        error_state(f"Could not load alerts: {exc}", _T)
        return

    high_risk = [m for m in overview if m["risk_category"] == "HIGH"]
    overdue = [m for m in overview if m["overdue_capa_count"] > 0]
    anomalous = [m for m in overview if m["m5_is_anomaly"]]
    stale = [m for m in overview if m["rescore_required"]]

    st.markdown(
        '<div class="alerts-header"><div class="alerts-eyebrow">Operational Alert Center</div>'
        '<h1>Alerts</h1>'
        '<p>A real aggregation of HIGH risk mines, overdue CAPA, M5 anomalies and stale risk scores.</p>'
        '<span class="page-context-badge">Current platform data · Not a separate stored entity</span></div>',
        unsafe_allow_html=True,
    )
    alert_specs = [
        ("HIGH RISK MINES", len(high_risk), "Requires immediate attention", _T["RISK"]["CRITICAL"] if high_risk else _T["RISK"]["LOW"]),
        ("MINES WITH OVERDUE CAPA", len(overdue), "Past-due corrective actions", _T["RISK"]["MEDIUM"] if overdue else _T["RISK"]["LOW"]),
        ("M5 ANOMALIES DETECTED", len(anomalous), "Simulated telemetry only", _T["RISK"]["MEDIUM"] if anomalous else _T["RISK"]["LOW"]),
        ("STALE RISK SCORES", len(stale), "Rescore required after CAPA closure", _T["RISK"]["MEDIUM"] if stale else _T["RISK"]["LOW"]),
    ]
    summary_html = "".join(
        f'<div class="alerts-metric" style="--metric-tone:{tone}">'
        f'<span class="alerts-metric-label">{label}</span><strong class="alerts-metric-value">{count}</strong>'
        f'<span class="m4-chart-caption">{detail if count else "No active alerts"}</span></div>'
        for label, count, detail, tone in alert_specs
    )
    st.markdown(f'<div class="alerts-summary">{summary_html}</div>', unsafe_allow_html=True)

    health_html = "".join(
        '<div class="alerts-health-item">'
        f'<span class="alerts-metric-label">{label}</span>'
        f'<strong class="alerts-metric-value" style="color:{tone}">{count}</strong></div>'
        for label, count, _, tone in alert_specs
    )
    st.markdown(
        '<div class="alerts-section"><h2>Alert health</h2></div>'
        f'<div class="alerts-health-grid">{health_html}</div>',
        unsafe_allow_html=True,
    )

    priority_col, categories_col = st.columns([1.7, 1], gap="large")
    with priority_col:
        st.markdown(
            '<div class="alerts-section"><h2>Priority alerts</h2>'
            '<p>Items requiring review, drawn from current mine records.</p></div>',
            unsafe_allow_html=True,
        )
        if not (high_risk or overdue or anomalous or stale):
            empty_state("No active alerts across any mine visible to this role.", _T, icon="✓")
        else:
            if high_risk:
                st.markdown('<div class="alerts-section"><h2>HIGH RISK MINES</h2><p>Requires attention</p></div>', unsafe_allow_html=True)
                for mine in high_risk:
                    st.markdown(
                        f'<div class="alerts-queue-item" style="--alert-tone:{_T["RISK"]["CRITICAL"]}">'
                        f'{severity_badge("HIGH", _T)} <strong>{escape(str(mine["name"]))}</strong>'
                        '<div class="map-detail-grid" style="margin-top:8px">'
                        f'<div><span class="map-detail-label">M3 operational risk score</span><strong>{escape(str(mine["risk_score"]))}</strong></div>'
                        f'<div><span class="map-detail-label">Open CAPA</span><strong>{mine["open_capa_count"]}</strong></div>'
                        '</div></div>',
                        unsafe_allow_html=True,
                    )
            for title, records, field, label, tone in [
                ("OVERDUE CAPA", overdue, "overdue_capa_count", "Overdue CAPA items", _T["RISK"]["MEDIUM"]),
                ("M5 ANOMALY", anomalous, "m5_anomaly_score", "M5 anomaly score · SIMULATED", _T["ACCENT"]),
                ("STALE RISK SCORE", stale, None, "CAPA closed since last scoring", _T["RISK"]["MEDIUM"]),
            ]:
                if records:
                    st.markdown(f'<div class="alerts-section"><h2>{title}</h2></div>', unsafe_allow_html=True)
                    for mine in records:
                        value = mine[field] if field else "Rebuild required"
                        st.markdown(
                            f'<div class="alerts-queue-item" style="--alert-tone:{tone}">'
                            f'<strong>{escape(str(mine["name"]))}</strong>'
                            f'<div class="m4-chart-caption">{label}: {escape(str(value))}</div></div>',
                            unsafe_allow_html=True,
                        )

    with categories_col:
        st.markdown(
            '<div class="alerts-section"><h2>Alert categories</h2>'
            '<p>Count by existing alert type.</p></div>',
            unsafe_allow_html=True,
        )
        maximum = max((count for _, count, _, _ in alert_specs), default=0)
        category_rows = "".join(
            '<div class="alerts-category-row">'
            f'<span>{label} {"· No active alerts" if count == 0 else ""}</span><strong>{count}</strong></div>'
            f'<div style="height:4px;background:{_T["SURFACE_SUNKEN"]};border-radius:4px;margin:0 0 6px">'
            f'<div style="height:4px;width:{(count / maximum * 100) if maximum else 0:.2f}%;background:{tone};border-radius:4px"></div></div>'
            for label, count, _, tone in alert_specs
        )
        st.markdown(f'<div class="alerts-card">{category_rows}</div>', unsafe_allow_html=True)

    if overdue:
        st.markdown('<div class="alerts-section"><h2>Mines with overdue CAPA items</h2></div>', unsafe_allow_html=True)
        st.dataframe(
            [{"Mine": m["name"], "Overdue count": m["overdue_capa_count"]} for m in overdue],
            use_container_width=True, hide_index=True,
        )
    if anomalous:
        st.markdown('<div class="alerts-section"><h2>M5 sensor anomalies · SIMULATED telemetry</h2></div>', unsafe_allow_html=True)
        st.dataframe(
            [{"Mine": m["name"], "Anomaly score": m["m5_anomaly_score"]} for m in anomalous],
            use_container_width=True, hide_index=True,
        )
    if stale:
        st.markdown('<div class="alerts-section"><h2>Risk scores needing a rebuild</h2></div>', unsafe_allow_html=True)
        st.dataframe([{"Mine": m["name"]} for m in stale], use_container_width=True, hide_index=True)


def render_grievances(client: ApiClient, user: dict):
    st.markdown(
        '<div class="grievance-header"><div class="grievance-eyebrow">Grievance &amp; Community Safety</div>'
        '<h1>Grievances</h1><p>Receive, track and resolve worker and community concerns.</p>'
        '<span class="page-context-badge">COMMUNITY SAFETY</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="grievance-note">Worker/community grievances have an SLA deadline set on filing. '
        "Filing anonymously never stores the filer's identity.</div>",
        unsafe_allow_html=True,
    )

    form_col, guidance_col = st.columns([1.5, 1], gap="medium")
    with form_col:
        with st.container(border=True):
            st.markdown(
                '<div class="grievance-section"><h2>FILE A GRIEVANCE</h2>'
                '<p>Submit a worker or community concern.</p></div>',
                unsafe_allow_html=True,
            )
            with st.expander("Open grievance form", expanded=False):
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
    with guidance_col:
        st.markdown(
            '<div class="grievance-card"><div class="grievance-section"><h2>HOW IT WORKS</h2></div>'
            '<div class="approval-step"><strong>01 · File concern</strong></div>'
            '<div class="approval-step"><strong>02 · SLA deadline assigned</strong></div>'
            '<div class="approval-step"><strong>03 · Concern reviewed</strong></div>'
            '<div class="approval-step"><strong>04 · Resolution tracked</strong></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="grievance-note"><strong>PRIVACY PROTECTION</strong><br>'
            "Anonymous filing does not store the filer's identity.</div>",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="grievance-section"><h2>GRIEVANCE STATUS</h2></div>', unsafe_allow_html=True)
    with st.container(border=True):
        col1, col2 = st.columns([1, 1], gap="medium", vertical_alignment="bottom")
        with col1:
            status_filter = st.selectbox("Status filter", ["All", "OPEN", "IN_PROGRESS", "ESCALATED", "RESOLVED"])
        with col2:
            if st.button("Run SLA check now", use_container_width=True):
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

    from collections import Counter
    grievance_status_counts = Counter(g["status"] for g in grievances)
    breached_count = sum(1 for g in grievances if g["sla_breached"])
    grievance_metrics = [
        ("FILTERED GRIEVANCES", len(grievances), _T["ACCENT"]),
        ("OPEN", grievance_status_counts.get("OPEN", 0), _T["RISK"]["MEDIUM"]),
        ("IN PROGRESS", grievance_status_counts.get("IN_PROGRESS", 0), _T["ACCENT"]),
        ("RESOLVED", grievance_status_counts.get("RESOLVED", 0), _T["RISK"]["LOW"]),
        ("SLA BREACHED", breached_count, _T["RISK"]["CRITICAL"] if breached_count else _T["RISK"]["LOW"]),
    ]
    grievance_metric_html = "".join(
        f'<div class="grievance-metric" style="--metric-tone:{tone}">'
        f'<span class="grievance-metric-label">{label}</span><strong class="grievance-metric-value">{count}</strong></div>'
        for label, count, tone in grievance_metrics
    )
    st.markdown(f'<div class="grievance-summary">{grievance_metric_html}</div>', unsafe_allow_html=True)

    if not grievances:
        st.markdown('<div class="grievance-section"><h2>RECENT / FILTERED GRIEVANCES</h2></div>', unsafe_allow_html=True)
        empty_state("NO GRIEVANCES FOUND · No grievance records match the current filter.", _T)
        return

    st.markdown(
        '<div class="grievance-section"><h2>RECENT / FILTERED GRIEVANCES</h2>'
        '<p>Existing grievance records matching the selected status.</p></div>',
        unsafe_allow_html=True,
    )
    for g in grievances:
        status_badge = severity_badge("ESCALATED" if g["sla_breached"] else g["status"], _T)
        grievance_tone = _T["RISK"]["CRITICAL"] if g["sla_breached"] else _T["RISK"]["LOW"] if g["status"] == "RESOLVED" else _T["ACCENT"]
        with st.expander(f"{g['category']} — {g['status']} {'(anonymous)' if g['is_anonymous'] else ''}"):
            st.markdown(
                f'<div class="grievance-item" style="--grievance-tone:{grievance_tone}">'
                f'<strong>{escape(str(g["category"]).replace("_", " "))}</strong> {status_badge}'
                f'<div class="m4-chart-caption">SLA due: {escape(str(g["sla_due_at"]))} · '
                f'{"BREACHED, " + str(g["days_overdue"]) + " day(s) overdue" if g["sla_breached"] else "within SLA"} · '
                f'escalation level {escape(str(g["escalation_level"]))}</div></div>',
                unsafe_allow_html=True,
            )
            st.write(g["description"])
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
    st.markdown(
        '<div class="approval-header"><div class="approval-eyebrow">Approvals &amp; Governance</div>'
        '<h1>Approvals</h1><p>Controlled three-stage sign-off for corrective actions.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="approval-workflow">'
        '<div class="approval-step"><span class="approval-eyebrow">01</span><br><strong>MINE MANAGER</strong><br><span class="m4-chart-caption">Initial review</span></div>'
        '<div class="approval-step"><span class="approval-eyebrow">02</span><br><strong>SUBSIDIARY GM</strong><br><span class="m4-chart-caption">Subsidiary approval</span></div>'
        '<div class="approval-step"><span class="approval-eyebrow">03</span><br><strong>CORPORATE OFFICE</strong><br><span class="m4-chart-caption">Final sign-off</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<div class="approval-section"><h2>REQUEST APPROVAL</h2></div>', unsafe_allow_html=True)
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
            else:
                st.caption("No open CAPA items for this mine.")

    try:
        chains = client.get("/api/v1/approvals")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    from collections import Counter
    approval_counts = Counter(c["final_decision"] for c in chains)
    approval_metric_specs = [
        ("PENDING", approval_counts.get("PENDING", 0), _T["RISK"]["MEDIUM"]),
        ("IN PROGRESS", sum(1 for c in chains if c["final_decision"] == "PENDING" and c["current_stage"]), _T["ACCENT"]),
        ("COMPLETED", approval_counts.get("APPROVED", 0), _T["RISK"]["LOW"]),
    ]
    approval_metrics_html = "".join(
        f'<div class="audit-metric" style="--metric-tone:{tone}"><span class="audit-metric-label">{label}</span>'
        f'<strong class="audit-metric-value">{count}</strong></div>'
        for label, count, tone in approval_metric_specs
    )
    st.markdown(f'<div class="audit-summary">{approval_metrics_html}</div>', unsafe_allow_html=True)
    if not chains:
        empty_state("No approval chains yet.", _T)
        return

    st.markdown('<div class="approval-section"><h2>APPROVAL CHAINS</h2></div>', unsafe_allow_html=True)
    for c in chains:
        decision_badge = severity_badge(c["final_decision"], _T)
        with st.expander(f"{c['reason']} "
                         + (f" (awaiting {c['current_stage']})" if c["current_stage"] else "")):
            st.markdown(
                '<div class="approval-card"><span class="map-detail-label">FINAL DECISION</span>'
                + decision_badge + '</div>',
                unsafe_allow_html=True,
            )
            stage_columns = st.columns(max(1, len(c["steps"])), gap="small")
            for stage_col, step in zip(stage_columns, c["steps"]):
                stage_badge = severity_badge(step["decision"], _T)
                with stage_col:
                    st.markdown(
                        '<div class="approval-step">'
                        f'<strong>{escape(str(step["stage"]).replace("_", " "))}</strong><br>{stage_badge}'
                        + (f'<div class="m4-chart-caption">Waiting {escape(str(step["waiting_hours"]))}h</div>' if step["waiting_hours"] is not None else '')
                        + '</div>',
                        unsafe_allow_html=True,
                    )
            for step in c["steps"]:
                waiting = f" - waiting {step['waiting_hours']}h" if step["waiting_hours"] is not None else ""
                if step["note"]:
                    st.caption(f"{step['stage']}{waiting}: {step['note']}")
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
    try:
        contractors = client.get("/api/v1/contractors")
    except ApiError as exc:
        error_state(str(exc), _T)
        return
    if not contractors:
        st.markdown(
            '<div class="contractor-header"><div class="contractor-eyebrow">Contractor Governance</div>'
            '<h1>Contractor Passport</h1><p>Track contractor status, mine engagements and compliance exposure.</p></div>',
            unsafe_allow_html=True,
        )
        empty_state("NO CONTRACTORS AVAILABLE. No contractor records are currently available for this view.", _T)
        return

    from collections import Counter
    st.markdown(
        '<div class="contractor-header"><div class="contractor-eyebrow">Contractor Governance</div>'
        '<h1>Contractor Passport</h1><p>Track contractor status, mine engagements and compliance exposure.</p>'
        '<span class="page-context-badge">CONTRACTOR CONTROL</span></div>',
        unsafe_allow_html=True,
    )
    status_counts = Counter(c.get("status", "UNKNOWN") for c in contractors)
    contractor_metrics = [
        ("TOTAL CONTRACTORS", len(contractors), _T["ACCENT"]),
        ("ACTIVE", status_counts.get("ACTIVE", 0), _T["RISK"]["LOW"]),
        ("DEBARRED", status_counts.get("DEBARRED", 0), _T["RISK"]["CRITICAL"] if status_counts.get("DEBARRED", 0) else _T["TEXT_MUTED"]),
    ]
    contractor_metric_html = "".join(
        f'<div class="contractor-metric" style="--metric-tone:{tone}">'
        f'<span class="contractor-metric-label">{label}</span><strong class="contractor-metric-value">{count}</strong></div>'
        for label, count, tone in contractor_metrics
    )
    st.markdown(f'<div class="contractor-summary">{contractor_metric_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="contractor-section"><h2>CONTRACTOR DIRECTORY</h2>'
        '<p>All contractor records returned for the current view.</p></div>',
        unsafe_allow_html=True,
    )
    directory_html = "".join(
        '<div class="contractor-card">'
        f'<span class="contractor-status">{escape(str(c.get("status") or "UNKNOWN"))}</span>'
        f'<strong class="map-detail-value">{escape(str(c.get("name") or "Not specified"))}</strong>'
        f'<span class="map-detail-label">{escape(str(c.get("code") or "Not specified"))}</span></div>'
        for c in contractors
    )
    st.markdown(f'<div class="contractor-detail-grid">{directory_html}</div>', unsafe_allow_html=True)

    names = {f"{c['name']} ({c['code']}) - {c['status']}": c["contractor_id"] for c in contractors}
    st.markdown('<div class="contractor-section"><h2>SELECTED CONTRACTOR</h2></div>', unsafe_allow_html=True)
    chosen = st.selectbox("Contractor", list(names), key="contractor_passport_selected")
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

    selected_contractor = next(c for c in contractors if c["contractor_id"] == names[chosen])
    provenance_note = str(detail.get("note") or "")
    is_demo = "DEMO" in (str(selected_contractor.get("code", "")) + " " + provenance_note).upper() or "SYNTHETIC" in provenance_note.upper()
    status_color = _T["RISK"]["CRITICAL"] if detail["status"] == "DEBARRED" else _T["RISK"]["LOW"] if detail["status"] == "ACTIVE" else _T["TEXT_MUTED"]
    hero_html = (
        '<div class="contractor-card">'
        '<span class="map-detail-label">SELECTED CONTRACTOR</span>'
        f'<strong class="map-detail-value">{escape(str(detail.get("name") or "Not specified"))}</strong>'
        f'<span class="contractor-status" style="color:{status_color}">{escape(str(detail.get("status") or "Unknown"))}</span>'
        f'<span class="m4-chart-caption">{escape(str(detail.get("code") or "Not specified"))}'
        + (' · DEMO / SYNTHETIC DATA' if is_demo else '')
        + '</span></div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    open_capa = sum(site["open_capa_count_during_engagement"] for site in detail["sites"])
    capa_during = sum(site["capa_count_during_engagement"] for site in detail["sites"])
    detail_metrics = [
        ("STATUS", detail["status"], status_color),
        ("SITES ENGAGED", len(detail["sites"]), _T["ACCENT"]),
        ("DOCUMENTS ON FILE", detail["document_count"], _T["ACCENT"]),
        ("OPEN CAPA", open_capa, _T["RISK"]["MEDIUM"] if open_capa else _T["RISK"]["LOW"]),
    ]
    detail_metric_html = "".join(
        f'<div class="contractor-metric" style="--metric-tone:{tone}">'
        f'<span class="contractor-metric-label">{label}</span><strong class="contractor-metric-value">{escape(str(value))}</strong></div>'
        for label, value, tone in detail_metrics
    )
    st.markdown(f'<div class="contractor-summary">{detail_metric_html}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="contractor-section"><h2>MINE ENGAGEMENTS</h2>'
        '<p>Sites and mines where this contractor has an active or historical engagement.</p></div>',
        unsafe_allow_html=True,
    )
    if detail["sites"]:
        for site in detail["sites"]:
            active_label = "ACTIVE" if site["is_active"] else "ENDED"
            active_color = _T["RISK"]["LOW"] if site["is_active"] else _T["TEXT_MUTED"]
            engagement_fields = [
                ("START", site["contract_start"] or "Not recorded"),
                ("END", site["contract_end"] or "Not recorded"),
                ("CAPA DURING ENGAGEMENT", site["capa_count_during_engagement"]),
                ("OPEN CAPA", site["open_capa_count_during_engagement"]),
            ]
            engagement_html = "".join(
                f'<div><span class="contractor-detail-label">{label}</span>'
                f'<strong class="contractor-detail-value">{escape(str(value))}</strong></div>'
                for label, value in engagement_fields
            )
            st.markdown(
                '<div class="contractor-card">'
                f'<span class="contractor-status" style="color:{active_color}">{active_label}</span>'
                f'<strong class="map-detail-value">{escape(str(site["mine_name"]))}</strong>'
                f'<div class="contractor-engagement-grid">{engagement_html}</div></div>',
                unsafe_allow_html=True,
            )
    else:
        empty_state("No mine engagements are recorded for this contractor.", _T)

    exposure_col, documents_col = st.columns(2, gap="medium")
    with exposure_col:
        st.markdown(
            '<div class="contractor-section"><h2>COMPLIANCE EXPOSURE</h2></div>'
            f'<div class="contractor-card"><div class="contractor-detail-grid">'
            f'<div><span class="contractor-detail-label">CAPA DURING ENGAGEMENT</span><strong>{capa_during}</strong></div>'
            f'<div><span class="contractor-detail-label">OPEN CAPA</span><strong>{open_capa}</strong></div></div>'
            '<div class="contractor-note"><strong>DATA INTERPRETATION</strong><br>'
            f'{escape(provenance_note)}</div></div>',
            unsafe_allow_html=True,
        )
    with documents_col:
        st.markdown(
            '<div class="contractor-section"><h2>CONTRACTOR DOCUMENTS</h2></div>',
            unsafe_allow_html=True,
        )
        if detail["document_count"]:
            st.markdown(
                f'<div class="contractor-card"><strong>{detail["document_count"]}</strong> documents on file. '
                'Document details are not included in the current contractor response.</div>',
                unsafe_allow_html=True,
            )
        else:
            empty_state("NO CONTRACTOR DOCUMENTS RECORDED", _T)


def render_settings(client: ApiClient, user: dict):
    st.markdown(
        '<div class="settings-header"><div class="settings-eyebrow">System Administration</div>'
        '<h1>System &amp; Account Settings</h1>'
        '<p>Account identity and role-aware access information.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="settings-grid">', unsafe_allow_html=True)
    profile_col, access_col = st.columns(2, gap="medium")
    with profile_col:
        with st.container(border=True):
            st.markdown('<div class="settings-section"><h2>YOUR PROFILE</h2></div>', unsafe_allow_html=True)
            role_badge = severity_badge(user["role"], _T)
            mine_association = user.get("mine_id") or "none (org-wide role)"
            st.markdown(
                '<div class="map-detail-grid">'
                f'<div><span class="map-detail-label">EMAIL</span><strong>{escape(str(user["email"]))}</strong></div>'
                f'<div><span class="map-detail-label">ROLE</span>{role_badge}</div>'
                f'<div><span class="map-detail-label">MINE ASSOCIATION</span><strong class="audit-hash">{escape(str(mine_association))}</strong></div>'
                '</div>',
                unsafe_allow_html=True,
            )
    with access_col:
        st.markdown(
            '<div class="settings-card"><div class="settings-section"><h2>ACCESS CONTROL</h2></div>'
            'Navigation is role-aware. Backend authorization remains authoritative for every protected action.'
            '</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)
    st.caption("Navigation is hidden per role for convenience only. The backend enforces every permission independently.")
    if user["role"] == "ADMIN":
        st.markdown('<div class="settings-section"><h2>USER DIRECTORY · ADMIN ONLY</h2></div>', unsafe_allow_html=True)
        try:
            users = client.get("/api/v1/auth/users")
            with st.container(border=True):
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
    st.markdown(
        '<div class="report-header"><div class="report-eyebrow">M6 · Statutory Reporting</div>'
        '<h1>Statutory Reporting Center</h1>'
        '<p>Generate compliance reports from the application’s current mine, CAPA and statutory records.</p></div>',
        unsafe_allow_html=True,
    )
    try:
        mines = client.get("/api/v1/mines")
    except ApiError as exc:
        error_state(f"Could not load mines: {exc}", _T)
        return
    if not mines:
        empty_state("No mines available.", _T)
        return
    mine_names = {m["name"]: m["id"] for m in mines}
    report_control_col, lifecycle_col = st.columns([1.3, 1], gap="medium")
    with report_control_col:
        with st.container(border=True):
            st.markdown('<div class="report-section"><h2>GENERATE STATUTORY REPORT</h2></div>', unsafe_allow_html=True)
            chosen = st.selectbox("Mine", list(mine_names), key="report_mine")
            mine_id = mine_names[chosen]
            generate = st.button("Generate report", type="primary", use_container_width=True)
    with lifecycle_col:
        st.markdown(
            '<div class="report-card"><div class="report-section"><h2>REPORT LIFECYCLE</h2></div>'
            '<div class="approval-step">01 · Select mine</div><div class="approval-step">02 · Validate current records</div>'
            '<div class="approval-step">03 · Generate representative report</div><div class="approval-step">04 · PDF download</div>'
            '<div class="approval-step">05 · Audit trail</div></div>',
            unsafe_allow_html=True,
        )

    if generate:
        try:
            result = client.post("/api/v1/reports/generate", params={"mine_id": mine_id})
        except ApiError as exc:
            error_state(f"Report generation failed: {exc}", _T)
            return
        st.markdown('<div class="report-section"><h2>REPORT READY</h2></div>', unsafe_allow_html=True)
        st.warning("REPRESENTATIVE STATUTORY RETURN - not an official DGMS/MSHA form.")
        import base64
        pdf_bytes = base64.b64decode(result["pdf_base64"])
        st.download_button("Download PDF", data=pdf_bytes, file_name="anthryx_report.pdf", mime="application/pdf")
        with st.container(border=True):
            st.json(result["summary"])


PAGES = {
    "Overview": render_overview, "M3 Risk": render_risk, "M5 Anomaly": render_anomaly,
    "M4 CAPA": render_capa, "M1 Documents": render_documents, "M0 Compliance": render_compliance,
    "Voice Incident": render_voice, "Audit Ledger": render_audit, "Risk Map": render_gis,
    "Alerts": render_alerts, "Grievances": render_grievances, "Approvals": render_approvals,
    "Contractor Passport": render_contractors, "Settings": render_settings, "Reports": render_reports,
    "Compliance Copilot": render_copilot,
}

NAV_GROUPS = [
    ("OVERVIEW", ["Overview"]),
    ("RISK & MONITORING", ["M3 Risk", "M5 Anomaly", "Risk Map", "Alerts"]),
    ("COMPLIANCE", ["M4 CAPA", "M0 Compliance", "M1 Documents", "Compliance Copilot"]),
    ("OPERATIONS", ["Voice Incident", "Contractor Passport", "Grievances"]),
    ("GOVERNANCE", ["Audit Ledger", "Approvals", "Reports", "Settings"]),
]


def _theme_toggle():
    label = "Switch to dark theme" if _THEME_MODE == "light" else "Switch to light theme"
    if st.button(label, key=f"theme_toggle_{_THEME_MODE}"):
        st.query_params["theme"] = "dark" if _THEME_MODE == "light" else "light"
        st.rerun()


def _render_login(client: ApiClient) -> None:
    st.title("ANTHRYX AI")
    st.subheader("Sign in")
    st.caption("Choose a demo role or enter an account ID, then provide its password.")
    st.caption("Check readme file for password")
    role_name = st.selectbox("Demo account", list(DEMO_ACCOUNTS))
    with st.form("login_form"):
        email = st.text_input(
            "Account ID", value=DEMO_ACCOUNTS[role_name], key=f"login_email_{role_name}"
        )
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            client.login(email.strip(), password)
            st.session_state.user = client.me()
            st.session_state.pop("dashboard_page", None)
            st.rerun()
        except ApiError as exc:
            client.token = None
            st.error(f"Sign-in failed: {exc}")


def main() -> None:
    client = _client()
    if "user" not in st.session_state:
        _render_login(client)
        return

    user = st.session_state.user
    role = user["role"]
    available = ROLE_PAGES.get(role, ["Overview"])
    page = st.session_state.get("dashboard_page", "Overview")
    if page not in available:
        page = available[0]
        st.session_state["dashboard_page"] = page

    with st.sidebar:
        st.markdown(
            '<div class="overview-sidebar-brand"><strong>ANTHRYX AI</strong>'
            '<span>Coal Mine Compliance &amp; Governance</span></div>'
            f'<div class="overview-sidebar-subtitle">{escape(str(user.get("email", "Signed-in user")))} · {escape(str(role)).replace("_", " ")}</div>',
            unsafe_allow_html=True,
        )
        _theme_toggle()
        if st.button("Switch user", use_container_width=True):
            client.token = None
            st.session_state.pop("user", None)
            st.session_state.pop("dashboard_page", None)
            st.rerun()
        st.divider()
        grouped_pages = {name for _, names in NAV_GROUPS for name in names}
        for group, names in NAV_GROUPS:
            visible_names = [name for name in names if name in available]
            if not visible_names:
                continue
            st.markdown(f'<div class="overview-nav-group">{escape(group)}</div>', unsafe_allow_html=True)
            for name in visible_names:
                if st.button(
                    name, key=f"nav_{name}", use_container_width=True,
                    type="primary" if page == name else "secondary",
                ):
                    st.session_state["dashboard_page"] = name
                    st.rerun()
        ungrouped = [name for name in available if name not in grouped_pages]
        if ungrouped:
            st.markdown('<div class="overview-nav-group">OTHER</div>', unsafe_allow_html=True)
            for name in ungrouped:
                if st.button(name, key=f"nav_{name}", use_container_width=True, type="primary" if page == name else "secondary"):
                    st.session_state["dashboard_page"] = name
                    st.rerun()

    fn = PAGES[page]
    if page in ("Overview", "M4 CAPA", "Settings", "Grievances"):
        fn(client, user)
    else:
        fn(client)


if __name__ == "__main__":
    main()
