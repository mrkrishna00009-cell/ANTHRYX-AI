"""Reusable UI components for the ANTHRYX AI dashboard.

Real, shared components rather than page-specific duplicated markup -
every page that shows a KPI number, a status badge, a section heading,
an empty/error state, or a timeline row uses these functions, so they
look and behave identically everywhere. All take the active theme's
token dict (from theme.get_theme(mode)) so they render correctly in
light and dark without page-specific overrides.
"""
from __future__ import annotations

import streamlit as st


def kpi_row(items: list[dict], theme: dict) -> None:
    """items: list of {"label": str, "value": str|int, "tone": "neutral"|"good"|"warn"|"bad", "hint": str|None}.
    Renders as a row of equal-width cards - a real, shared component,
    not a one-off per page."""
    tone_colors = {
        "neutral": theme["ACCENT"], "good": theme["RISK"]["LOW"],
        "warn": theme["RISK"]["MEDIUM"], "bad": theme["RISK"]["CRITICAL"],
    }
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        color = tone_colors.get(item.get("tone", "neutral"), theme["ACCENT"])
        hint_html = (
            f'<div style="font-size:0.78rem;color:{theme["TEXT_MUTED"]};margin-top:2px;">{item["hint"]}</div>'
            if item.get("hint") else ""
        )
        col.markdown(
            f"""
            <div style="border:1px solid {theme['BORDER']};border-left:3px solid {color};
                       border-radius:4px;background:{theme['SURFACE_SUNKEN']};
                       padding:12px 14px;min-height:88px;">
              <div style="font-size:0.78rem;color:{theme['TEXT_MUTED']};text-transform:uppercase;
                         letter-spacing:0.03em;">{item['label']}</div>
              <div style="font-size:1.65rem;font-weight:600;color:{theme['TEXT']};line-height:1.3;">
                {item['value']}
              </div>
              {hint_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def section_header(title: str, caption: str | None, theme: dict) -> None:
    """A consistent section header - title + optional one-line caption -
    used instead of ad hoc st.subheader/st.caption pairs so every page's
    section headings look and space identically."""
    st.markdown(
        f"""
        <div style="margin-top:18px;margin-bottom:6px;">
          <div style="font-size:1.05rem;font-weight:600;color:{theme['TEXT']};
                     border-bottom:2px solid {theme['ACCENT']};display:inline-block;
                     padding-bottom:3px;">{title}</div>
          {f'<div style="font-size:0.86rem;color:{theme["TEXT_MUTED"]};margin-top:4px;">{caption}</div>' if caption else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(message: str, theme: dict, icon: str = "○") -> None:
    """One consistent look for 'nothing to show here yet' across every
    page - never a silent blank region."""
    st.markdown(
        f"""
        <div style="border:1px dashed {theme['BORDER']};border-radius:4px;
                   padding:22px;text-align:center;color:{theme['TEXT_MUTED']};
                   background:{theme['SURFACE_SUNKEN']};">
          <div style="font-size:1.3rem;margin-bottom:4px;">{icon}</div>
          {message}
        </div>
        """,
        unsafe_allow_html=True,
    )


def error_state(message: str, theme: dict) -> None:
    """One consistent look for a genuine backend/API failure - distinct
    from empty_state, so a user never confuses 'nothing here' with
    'something broke'."""
    st.markdown(
        f"""
        <div style="border:1px solid {theme['RISK']['CRITICAL']};border-left:4px solid {theme['RISK']['CRITICAL']};
                   border-radius:4px;padding:14px 16px;background:{theme['SURFACE_SUNKEN']};color:{theme['TEXT']};">
          <strong style="color:{theme['RISK']['CRITICAL']};">Request failed</strong><br/>{message}
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_timestamp(iso_string: str | None) -> str:
    """Consistent, readable timestamp formatting - never a raw ISO string
    with microseconds shown to a user. Falls back to the original string
    if it doesn't parse (never hides a real value behind a formatting error)."""
    if not iso_string:
        return "-"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except (ValueError, TypeError):
        return iso_string


def severity_badge(level: str | None, theme: dict) -> str:
    """Returns an inline HTML span - callers embed it in a markdown
    string or a dataframe cell. A consistent visual for LOW/MEDIUM/HIGH/
    CRITICAL and COMPLIANT/NON_COMPLIANT/ESCALATED wherever it appears."""
    if not level:
        return f'<span style="color:{theme["TEXT_MUTED"]};">-</span>'
    level_upper = level.upper()
    color_map = {
        "LOW": theme["RISK"]["LOW"], "COMPLIANT": theme["RISK"]["LOW"], "CLOSED": theme["RISK"]["LOW"],
        "VERIFIED": theme["RISK"]["LOW"], "RESOLVED": theme["RISK"]["LOW"], "APPROVED": theme["RISK"]["LOW"],
        "MEDIUM": theme["RISK"]["MEDIUM"], "IN_PROGRESS": theme["RISK"]["MEDIUM"], "PENDING": theme["RISK"]["MEDIUM"],
        "HIGH": theme["RISK"]["HIGH"], "OPEN": theme["RISK"]["HIGH"],
        "CRITICAL": theme["RISK"]["CRITICAL"], "NON_COMPLIANT": theme["RISK"]["CRITICAL"],
        "ESCALATED": theme["RISK"]["CRITICAL"], "REJECTED": theme["RISK"]["CRITICAL"], "OVERDUE": theme["RISK"]["CRITICAL"],
    }
    color = color_map.get(level_upper, theme["TEXT_MUTED"])
    return (
        f'<span style="display:inline-block;padding:2px 9px;border-radius:10px;'
        f'background:{color}22;color:{color};font-size:0.78rem;font-weight:600;'
        f'border:1px solid {color}55;">{level_upper.replace("_", " ")}</span>'
    )


def timeline_event_row(event: dict, theme: dict) -> None:
    """One consistent visual row per timeline event - what happened, why,
    and its current status - never a bare dataframe row."""
    badge = severity_badge(event.get("status") or event.get("severity"), theme)
    st.markdown(
        f"""
        <div style="border-left:3px solid {theme['BORDER']};padding:6px 0 6px 12px;margin-bottom:6px;">
          <span style="color:{theme['TEXT_MUTED']};font-size:0.8rem;">{event['timestamp'][:19].replace('T',' ')}</span>
          &nbsp;&middot;&nbsp;
          <strong style="color:{theme['TEXT']};">{event['event_type'].replace('_', ' ').title()}</strong>
          &nbsp;{badge}
          <div style="color:{theme['TEXT_MUTED']};font-size:0.88rem;margin-top:2px;">{event['explanation']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
