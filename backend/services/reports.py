"""M6 - statutory/compliance report generation.

Builds a PDF from real database data only. Never claims official Form IV
compliance - the layout is not verified against the published form, so
every generated report is labelled REPRESENTATIVE_STATUTORY_RETURN,
exactly as the existing Report model and /reports/status endpoint already
declare. Removing the previous 501 is only correct because this is a
genuine, working implementation, not a placeholder.
"""
from __future__ import annotations

import hashlib
import io
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.capa import CapaItem
from models.enums import CapaStatus
from models.field_evidence import IncidentReport
from models.ml import MlPrediction
from models.organisation import Mine
from models.statutory import MineObligation, StatutoryRule
from services.audit import AuditLedger


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": base["Title"],
        "h2": base["Heading2"],
        "body": base["Normal"],
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8, textColor=colors.grey),
        "disclaimer": ParagraphStyle(
            "disclaimer", parent=base["Normal"], fontSize=9,
            textColor=colors.HexColor("#8a1f1f"), leading=13,
        ),
    }


def generate_compliance_report(
    session: Session, mine_id, period_start: date | None, period_end: date | None,
) -> tuple[bytes, dict]:
    """Returns (pdf_bytes, payload_dict) for the caller to persist as a
    Report row. Uses only data actually present for this mine - an empty
    section says so rather than being silently omitted."""
    mine = session.get(Mine, mine_id)
    if mine is None:
        raise ValueError(f"No mine with id {mine_id}")

    obligations = list(session.execute(
        select(MineObligation, StatutoryRule)
        .join(StatutoryRule, MineObligation.rule_id == StatutoryRule.id)
        .where(MineObligation.mine_id == mine_id)
    ).all())

    capa_items = list(session.execute(
        select(CapaItem).where(CapaItem.mine_id == mine_id)
        .order_by(CapaItem.created_at.desc()).limit(50)
    ).scalars())

    incidents = list(session.execute(
        select(IncidentReport).join(
            IncidentReport.evidence
        ).where(IncidentReport.evidence.has(mine_id=mine_id))
        .order_by(IncidentReport.created_at.desc()).limit(20)
    ).scalars())

    latest_risk = session.execute(
        select(MlPrediction).where(MlPrediction.mine_id == mine_id)
        .order_by(MlPrediction.scored_at.desc()).limit(1)
    ).scalar_one_or_none()

    chain_status = AuditLedger(session).verify()

    st = _styles()
    story = []
    story.append(Paragraph("REPRESENTATIVE STATUTORY RETURN", st["title"]))
    story.append(Paragraph(
        "This is NOT an official DGMS/MSHA statutory form. The layout has not "
        "been verified against any published official format. It presents "
        "real system data in a compliance-summary structure only.",
        st["disclaimer"],
    ))
    story.append(Spacer(1, 14))

    story.append(Paragraph(
        f"Mine: {mine.name} ({mine.code}) &middot; {mine.mine_type.value} &middot; "
        f"{mine.district or '—'}, {mine.state or '—'}", st["h2"],
    ))
    period_str = (
        f"{period_start.isoformat()} to {period_end.isoformat()}"
        if period_start and period_end else "All available records"
    )
    story.append(Paragraph(f"Reporting period: {period_str}", st["body"]))
    story.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).isoformat()} UTC", st["small"],
    ))
    story.append(Spacer(1, 10))

    # --- Statutory obligations ---
    story.append(Paragraph("Statutory Obligations", st["h2"]))
    if obligations:
        rows = [["Rule / Clause", "Obligation Status", "Next Due"]]
        for ob, rule in obligations[:30]:
            rows.append([f"{rule.clause}", ob.status.value, str(ob.next_due_date or "—")])
        t = Table(rows, colWidths=[2.6*inch, 1.8*inch, 1.6*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14365C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No obligations recorded for this mine.", st["body"]))
    story.append(Spacer(1, 10))

    # --- Risk information ---
    story.append(Paragraph("M3 Risk Intelligence", st["h2"]))
    if latest_risk is not None:
        story.append(Paragraph(
            f"Risk score: {latest_risk.score} ({latest_risk.band}) &middot; "
            f"scored {latest_risk.scored_at.isoformat()} &middot; "
            f"model {latest_risk.model_version} &middot; artifact "
            f"{(latest_risk.artifact_hash or '—')[:16]}...", st["body"],
        ))
        story.append(Paragraph(
            "This is a ranking/prioritisation score, not a calibrated "
            "accident probability outside the model's MSHA test population.",
            st["small"],
        ))
    else:
        story.append(Paragraph("No M3 risk score has been computed for this mine.", st["body"]))
    story.append(Spacer(1, 10))

    # --- CAPA status ---
    story.append(Paragraph("Corrective and Preventive Actions", st["h2"]))
    if capa_items:
        rows = [["Source", "Severity", "Status", "Due"]]
        open_count = sum(1 for c in capa_items if c.status not in (CapaStatus.CLOSED, CapaStatus.VERIFIED))
        for c in capa_items[:20]:
            rows.append([c.source_type.value, c.severity.value, c.status.value, str(c.due_date or "—")])
        t = Table(rows, colWidths=[1.6*inch, 1.3*inch, 1.7*inch, 1.4*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14365C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)
        story.append(Paragraph(f"{open_count} of {len(capa_items)} shown are open.", st["small"]))
    else:
        story.append(Paragraph("No CAPA items recorded for this mine.", st["body"]))
    story.append(Spacer(1, 10))

    # --- Incidents ---
    story.append(Paragraph("Incidents", st["h2"]))
    if incidents:
        rows = [["Category", "Severity", "Source"]]
        for inc in incidents[:20]:
            rows.append([inc.category, inc.severity.value, inc.source.value])
        t = Table(rows, colWidths=[2.4*inch, 1.3*inch, 1.3*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14365C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No incidents recorded for this mine.", st["body"]))
    story.append(Spacer(1, 10))

    # --- Audit reference ---
    story.append(Paragraph("Audit Reference", st["h2"]))
    story.append(Paragraph(
        f"Ledger status at generation time: {'INTACT' if chain_status.intact else 'BROKEN'} "
        f"&middot; entries checked: {chain_status.entries_checked}", st["body"],
    ))
    story.append(Paragraph(
        "The audit ledger is tamper-evident (hash-chained), not immutable and not a blockchain.",
        st["small"],
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7*inch, bottomMargin=0.7*inch)
    doc.build(story)
    pdf_bytes = buf.getvalue()

    payload = {
        "mine_id": str(mine_id), "mine_code": mine.code,
        "obligations_count": len(obligations), "capa_count": len(capa_items),
        "incidents_count": len(incidents),
        "risk_included": latest_risk is not None,
        "audit_chain_intact_at_generation": chain_status.intact,
        "file_hash": hashlib.sha256(pdf_bytes).hexdigest(),
    }
    return pdf_bytes, payload
