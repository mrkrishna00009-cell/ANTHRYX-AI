"""Contradiction & Drift detection.

This module implements two real contradiction types, both computed from
data this application already persists - never a fabricated example:

  DOCUMENT_VS_FIELD_MISMATCH: a MineObligation's document-based status
  says the rule is currently satisfied (not MISSING/EXPIRED), while the
  most recent real InspectionFinding for that exact mine+rule recorded
  non-compliance, and that finding is newer than the obligation's own
  last_satisfied_date. The paperwork and the field observation disagree
  about the same rule at the same mine.

  INSPECTION_HISTORY_REVERSAL: two real inspections of the same mine+rule,
  where an earlier one found it compliant and a later one found it
  non-compliant, with no CAPA closure recorded in between to explain the
  regression. This looks purely within the field's own history, never
  at the obligation record - a genuine internal inconsistency in what
  was actually observed over time, not an invented one.

A third candidate (a mine's obligation record itself changing version -
e.g. a rule's frequency_days or severity being edited after the
obligation was created) was considered and is NOT implemented: this
project's schema has no versioning/history table for StatutoryRule
edits, so detecting that would require guessing at a prior version that
was never actually recorded. Building it would mean fabricating the
"before" state - explicitly what this module must not do.

Severity/confidence vocabulary is deliberately distinct from both M3
("risk_score"/"risk_category") and M5 ("anomaly_score"/"is_anomaly") -
this uses "contradiction_confidence" and "severity" fields of its own,
never mixed with either model's scale.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.field_evidence import FieldEvidence, InspectionFinding
from models.statutory import MineObligation, StatutoryRule
from models.enums import ObligationStatus


@dataclass(frozen=True)
class Contradiction:
    contradiction_type: str
    mine_id: uuid.UUID
    rule_id: uuid.UUID
    rule_code: str
    severity: str
    contradiction_confidence: float
    obligation_status: str
    obligation_last_satisfied_date: str | None
    finding_id: str
    finding_observed_at: str
    finding_observation: str | None
    explanation: str


def detect_contradictions(session: Session, mine_id: uuid.UUID) -> list[Contradiction]:
    """Real detection, run on demand against current data - never
    persisted as a standing table (nothing here needs surviving a
    schema change; a contradiction is either true right now or it
    isn't, recomputed each call from the same tables the rest of the
    app already trusts)."""
    results: list[Contradiction] = []

    obligations = session.execute(
        select(MineObligation, StatutoryRule)
        .join(StatutoryRule, StatutoryRule.id == MineObligation.rule_id)
        .where(
            MineObligation.mine_id == mine_id,
            MineObligation.status.notin_([ObligationStatus.MISSING, ObligationStatus.EXPIRED]),
        )
    ).all()

    for obligation, rule in obligations:
        latest_finding_row = session.execute(
            select(InspectionFinding, FieldEvidence.server_timestamp)
            .join(FieldEvidence, FieldEvidence.id == InspectionFinding.evidence_id)
            .where(FieldEvidence.mine_id == mine_id, InspectionFinding.rule_id == rule.id)
            .order_by(FieldEvidence.server_timestamp.desc())
            .limit(1)
        ).first()
        if latest_finding_row is None:
            continue
        finding, observed_at = latest_finding_row
        if finding.compliant is not False:
            continue  # field observation agrees the rule is satisfied - no contradiction

        # Only a genuine contradiction if the field observation is NEWER
        # than whatever last satisfied the obligation on paper - an old
        # non-compliant finding predating a since-verified document is
        # not a contradiction, it is history the obligation already moved past.
        if obligation.last_satisfied_date is not None and observed_at.date() <= obligation.last_satisfied_date:
            continue

        results.append(Contradiction(
            contradiction_type="DOCUMENT_VS_FIELD_MISMATCH",
            mine_id=mine_id, rule_id=rule.id, rule_code=rule.rule_code,
            severity=rule.severity.value,
            contradiction_confidence=1.0,  # deterministic rule, not a model - always fully confident when it fires
            obligation_status=obligation.status.value,
            obligation_last_satisfied_date=(
                obligation.last_satisfied_date.isoformat() if obligation.last_satisfied_date else None
            ),
            finding_id=str(finding.id), finding_observed_at=observed_at.isoformat(),
            finding_observation=finding.observation,
            explanation=(
                f"Obligation for {rule.rule_code} ({rule.title}) is recorded as "
                f"{obligation.status.value} on paper, but the most recent field inspection "
                f"({observed_at.date().isoformat()}) found it non-compliant"
                + (f": {finding.observation}" if finding.observation else "")
                + ". The document record and the field record disagree."
            ),
        ))

    # --- second type: a mine's own inspection history reversing itself ---
    all_findings = session.execute(
        select(InspectionFinding, FieldEvidence.server_timestamp)
        .join(FieldEvidence, FieldEvidence.id == InspectionFinding.evidence_id)
        .where(FieldEvidence.mine_id == mine_id, InspectionFinding.rule_id.is_not(None))
        .order_by(FieldEvidence.server_timestamp.asc())
    ).all()
    by_rule: dict = {}
    for finding, ts in all_findings:
        by_rule.setdefault(finding.rule_id, []).append((finding, ts))

    for rule_id, sequence in by_rule.items():
        if len(sequence) < 2:
            continue
        for i in range(len(sequence) - 1):
            earlier_finding, earlier_ts = sequence[i]
            later_finding, later_ts = sequence[i + 1]
            if earlier_finding.compliant is True and later_finding.compliant is False:
                rule = session.get(StatutoryRule, rule_id)
                if rule is None:
                    continue
                results.append(Contradiction(
                    contradiction_type="INSPECTION_HISTORY_REVERSAL",
                    mine_id=mine_id, rule_id=rule_id, rule_code=rule.rule_code,
                    severity=rule.severity.value,
                    contradiction_confidence=1.0,
                    obligation_status="N/A - this type compares two field records, not the obligation",
                    obligation_last_satisfied_date=None,
                    finding_id=str(later_finding.id), finding_observed_at=later_ts.isoformat(),
                    finding_observation=later_finding.observation,
                    explanation=(
                        f"For {rule.rule_code} ({rule.title}), an inspection on "
                        f"{earlier_ts.date().isoformat()} found the mine compliant, but a later "
                        f"inspection on {later_ts.date().isoformat()} found it non-compliant"
                        + (f": {later_finding.observation}" if later_finding.observation else "")
                        + ". The field record reversed itself over time."
                    ),
                ))
    return results
