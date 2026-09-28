"""M4 - CAPA lifecycle and escalation.

The state machine is explicit rather than a free-form status field so an
invalid jump (OPEN straight to CLOSED, say) is rejected instead of
silently accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from models.capa import CapaEvent, CapaItem
from models.enums import CapaStatus, Severity

#: Allowed transitions. ESCALATED is reachable from any open state and
#: returns to the working states, because escalating does not close an item.
ALLOWED_TRANSITIONS: dict[CapaStatus, frozenset[CapaStatus]] = {
    CapaStatus.OPEN: frozenset({CapaStatus.ASSIGNED, CapaStatus.ESCALATED}),
    CapaStatus.ASSIGNED: frozenset(
        {CapaStatus.IN_PROGRESS, CapaStatus.ESCALATED, CapaStatus.OPEN}
    ),
    CapaStatus.IN_PROGRESS: frozenset(
        {CapaStatus.EVIDENCE_SUBMITTED, CapaStatus.ESCALATED}
    ),
    CapaStatus.EVIDENCE_SUBMITTED: frozenset(
        {CapaStatus.VERIFIED, CapaStatus.IN_PROGRESS, CapaStatus.ESCALATED}
    ),
    CapaStatus.VERIFIED: frozenset({CapaStatus.CLOSED}),
    CapaStatus.CLOSED: frozenset(),
    CapaStatus.ESCALATED: frozenset(
        {CapaStatus.IN_PROGRESS, CapaStatus.EVIDENCE_SUBMITTED, CapaStatus.ASSIGNED}
    ),
}

#: Transitions that cannot be made without attached evidence.
REQUIRES_EVIDENCE = frozenset({CapaStatus.EVIDENCE_SUBMITTED})

#: Transitions that cannot be made without a written justification.
REQUIRES_NOTE = frozenset({CapaStatus.VERIFIED, CapaStatus.CLOSED})


@dataclass(frozen=True)
class EscalationRung:
    level: int
    days_relative_to_due: int
    notify_role: str
    description: str


#: Configurable ladder. Negative days fire before the due date.
DEFAULT_ESCALATION_LADDER: tuple[EscalationRung, ...] = (
    EscalationRung(1, -9999, "MINE_SAFETY_OFFICER", "on creation"),
    EscalationRung(2, -3, "MINE_MANAGER", "three days before due"),
    EscalationRung(3, 0, "SUBSIDIARY_HEAD", "on the due date"),
    EscalationRung(4, 7, "DGMS_REGULATOR", "seven days overdue"),
)


class InvalidTransition(ValueError):
    """Raised when a requested CAPA transition is not permitted."""


def transition(
    session: Session,
    capa: CapaItem,
    to_status: CapaStatus,
    actor_id: str | None = None,
    note: str | None = None,
    evidence_doc_id=None,
    progress_percent: int | None = None,
) -> CapaEvent:
    allowed = ALLOWED_TRANSITIONS.get(capa.status, frozenset())
    if to_status not in allowed:
        raise InvalidTransition(
            f"{capa.status.value} -> {to_status.value} is not a permitted "
            f"transition; allowed: {sorted(s.value for s in allowed) or 'none'}"
        )
    if to_status in REQUIRES_EVIDENCE and evidence_doc_id is None:
        raise InvalidTransition(
            f"{to_status.value} requires closure evidence to be attached"
        )
    if to_status in REQUIRES_NOTE and not (note or "").strip():
        raise InvalidTransition(f"{to_status.value} requires a written justification")

    from_status = capa.status
    capa.status = to_status
    now = datetime.now(timezone.utc)

    if to_status is CapaStatus.EVIDENCE_SUBMITTED:
        capa.closure_evidence_doc_id = evidence_doc_id
    if to_status is CapaStatus.VERIFIED:
        capa.verified_by = actor_id
        capa.verified_at = now
    if to_status is CapaStatus.ESCALATED:
        capa.escalation_level = max(capa.escalation_level, 1) + 0
        capa.escalated_at = now
    if progress_percent is not None:
        capa.progress_percent = max(0, min(100, progress_percent))
    if to_status is CapaStatus.CLOSED:
        capa.progress_percent = 100

    event = CapaEvent(
        capa_id=capa.id, from_status=from_status, to_status=to_status,
        actor_id=actor_id, note=note, evidence_doc_id=evidence_doc_id,
    )
    session.add(event)
    session.flush()
    return event


def due_escalation_level(
    capa: CapaItem, today: date, ladder=DEFAULT_ESCALATION_LADDER
) -> int:
    """Highest ladder rung whose trigger has been reached."""
    if capa.status in (CapaStatus.CLOSED, CapaStatus.VERIFIED) or capa.due_date is None:
        return 0
    days_past_due = (today - capa.due_date).days
    level = 0
    for rung in ladder:
        if days_past_due >= rung.days_relative_to_due:
            level = max(level, rung.level)
    if capa.severity is Severity.CRITICAL:
        level = max(level, ladder[-1].level)
    return level
