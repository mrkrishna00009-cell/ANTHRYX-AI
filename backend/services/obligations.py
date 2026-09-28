"""M0 - obligation evaluation.

The difference this module makes: a system that only reads uploaded
documents can report what has expired. A system with a rule registry can
also report what was never done at all. That second case is ``MISSING``,
and it is the one no existing portal surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.documents import Document
from models.enums import ObligationStatus, VerificationStatus
from models.organisation import Mine
from models.statutory import MineObligation, StatutoryRule

#: How far ahead an obligation counts as expiring rather than valid.
EXPIRING_SOON_DAYS = 30


@dataclass(frozen=True)
class ObligationAssessment:
    status: ObligationStatus
    days_until_due: int | None
    reason: str


def evaluate(
    obligation: MineObligation,
    today: date,
    has_verified_evidence: bool,
    has_unverified_evidence: bool = False,
    expiring_soon_days: int = EXPIRING_SOON_DAYS,
) -> ObligationAssessment:
    """Decide one obligation's status.

    Order matters. Evidence that exists but has not been verified by a
    human is PENDING_VERIFICATION, not VALID - OCR extraction is never
    compliance verification.
    """
    if not has_verified_evidence and not has_unverified_evidence:
        if obligation.next_due_date is None:
            return ObligationAssessment(
                ObligationStatus.MISSING, None,
                "applicable obligation with no evidence ever supplied",
            )
        delta = (obligation.next_due_date - today).days
        if delta < 0:
            return ObligationAssessment(
                ObligationStatus.MISSING, delta,
                "due date passed and no evidence was ever supplied",
            )
        return ObligationAssessment(
            ObligationStatus.MISSING, delta,
            "applicable obligation with no evidence ever supplied",
        )

    if has_unverified_evidence and not has_verified_evidence:
        return ObligationAssessment(
            ObligationStatus.PENDING_VERIFICATION, None,
            "evidence uploaded but not yet verified by an officer",
        )

    if obligation.next_due_date is None:
        return ObligationAssessment(
            ObligationStatus.VALID, None, "verified evidence, no expiry recorded"
        )

    delta = (obligation.next_due_date - today).days
    if delta < 0:
        return ObligationAssessment(
            ObligationStatus.EXPIRED, delta, f"overdue by {abs(delta)} days"
        )
    if delta <= expiring_soon_days:
        return ObligationAssessment(
            ObligationStatus.EXPIRING_SOON, delta, f"due in {delta} days"
        )
    return ObligationAssessment(
        ObligationStatus.VALID, delta, f"due in {delta} days"
    )


def applicable_rules(session: Session, mine: Mine) -> list[StatutoryRule]:
    rules = list(session.execute(
        select(StatutoryRule).where(StatutoryRule.is_active.is_(True))
    ).scalars())
    return [r for r in rules if r.applies_to(mine.mine_type.value)]


def sync_obligations_for_mine(session: Session, mine: Mine) -> list[MineObligation]:
    """Create a MineObligation row for every applicable rule.

    Obligations are materialised whether or not any document exists, which
    is what makes MISSING detectable.
    """
    existing = {
        o.rule_id: o
        for o in session.execute(
            select(MineObligation).where(MineObligation.mine_id == mine.id)
        ).scalars()
    }
    created: list[MineObligation] = []
    for rule in applicable_rules(session, mine):
        if rule.id in existing:
            continue
        obligation = MineObligation(
            mine_id=mine.id, rule_id=rule.id, status=ObligationStatus.MISSING
        )
        session.add(obligation)
        created.append(obligation)
    session.flush()
    return created


def refresh_status(
    session: Session, obligation: MineObligation, today: date | None = None
) -> ObligationAssessment:
    """Recompute one obligation against the documents currently on file."""
    today = today or date.today()
    docs = list(session.execute(
        select(Document).where(
            Document.mine_id == obligation.mine_id,
            Document.rule_id == obligation.rule_id,
        )
    ).scalars())

    verified = [d for d in docs if d.verification_status == VerificationStatus.VERIFIED]
    unverified = [
        d for d in docs
        if d.verification_status == VerificationStatus.PENDING_VERIFICATION
    ]

    if verified:
        latest = max(verified, key=lambda d: d.issue_date or date.min)
        if latest.issue_date:
            obligation.last_satisfied_date = latest.issue_date
        rule = obligation.rule or session.get(StatutoryRule, obligation.rule_id)
        if latest.expiry_date:
            obligation.next_due_date = latest.expiry_date
        elif rule and rule.frequency_days and latest.issue_date:
            obligation.next_due_date = latest.issue_date + timedelta(
                days=rule.frequency_days
            )
        obligation.satisfying_document_id = latest.id

    assessment = evaluate(
        obligation, today,
        has_verified_evidence=bool(verified),
        has_unverified_evidence=bool(unverified),
    )
    obligation.status = assessment.status
    obligation.note = assessment.reason
    session.flush()
    return assessment
