"""M4 - automatic CAPA escalation.

Runs the existing, unmodified escalation ladder (``services.capa.
DEFAULT_ESCALATION_LADDER`` / ``due_escalation_level``) as a real,
periodic job instead of only a value computed for display. No new
escalation policy is invented here - this module only performs the state
transition the existing ladder logic already says should happen.

Idempotency: a CAPA's ``escalation_level`` column is the durable marker
of the highest rung actually applied. The job only acts when the
ladder's computed level is STRICTLY HIGHER than what is already
recorded, so running it any number of times in a day - or being started
fresh after a restart - never re-fires the same escalation twice.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.capa import CapaEvent, CapaItem
from models.enums import CapaStatus
from services import capa as capa_service
from services.audit import AuditLedger

logger = logging.getLogger(__name__)

# actor_id columns (CapaEvent, AuditLogEntry) are real foreign keys to
# users.id, nullable. There is no persistent "system" user account, so
# the scheduler's actor_id is always None; "SYSTEM_SCHEDULER" is recorded
# in the free-text note/payload fields instead, never forced into a
# foreign key that expects a real user.
SCHEDULER_ACTOR_LABEL = "SYSTEM_SCHEDULER"


def run_escalation_check(session: Session, today: date | None = None) -> list[dict]:
    """The deterministic, directly callable job body. Returns a list of
    what it did, for tests and for logging - never raises for an
    individual CAPA's failure, so one bad row cannot block the rest."""
    today = today or datetime.now(timezone.utc).date()
    results = []

    candidates = session.execute(
        select(CapaItem).where(
            CapaItem.status.notin_([CapaStatus.CLOSED, CapaStatus.VERIFIED]),
            CapaItem.due_date.is_not(None),
        )
    ).scalars().all()

    for capa in candidates:
        try:
            level = capa_service.due_escalation_level(capa, today)
        except Exception:
            logger.exception("escalation check failed for CAPA %s", capa.id)
            continue

        if level <= capa.escalation_level:
            continue  # not overdue, or already at/above this rung - idempotent no-op

        previous_level = capa.escalation_level
        previous_status = capa.status

        if capa.status is not CapaStatus.ESCALATED:
            capa_service.transition(
                session, capa, CapaStatus.ESCALATED, actor_id=None,
                note=f"[{SCHEDULER_ACTOR_LABEL}] Automatically escalated to ladder level {level} "
                    f"(due {capa.due_date.isoformat()}, checked {today.isoformat()}).",
            )
        else:
            # Already ESCALATED from an earlier rung; record the level
            # increase without an illegal ESCALATED->ESCALATED transition.
            session.add(CapaEvent(
                capa_id=capa.id, from_status=CapaStatus.ESCALATED, to_status=CapaStatus.ESCALATED,
                actor_id=None,
                note=f"[{SCHEDULER_ACTOR_LABEL}] Escalation level raised {previous_level} -> {level} (still ESCALATED).",
            ))

        capa.escalation_level = level
        session.flush()

        AuditLedger(session).append(
            action="CAPA_AUTO_ESCALATED", entity_type="capa_item", entity_id=str(capa.id),
            actor_id=None,
            payload={
                "actor_label": SCHEDULER_ACTOR_LABEL,
                "mine_id": str(capa.mine_id), "previous_level": previous_level,
                "new_level": level, "previous_status": previous_status.value,
                "due_date": capa.due_date.isoformat(),
            },
        )
        results.append({"capa_id": str(capa.id), "previous_level": previous_level, "new_level": level})

    return results


def start_scheduler(sessionmaker):
    """Registers a REAL, live-interval background job - not merely a
    directly-callable function. Runs both the CAPA-escalation check and
    the grievance-SLA check on the same cadence, each independently
    idempotent (see run_escalation_check / grievances.run_sla_check).

    Never started during tests (app/main.py gates this on
    settings.scheduler_enabled, which the test suite's environment does
    not set) - tests invoke the check functions directly and
    deterministically instead. Interval is intentionally short
    (settings.scheduler_interval_seconds, default 30s) for a prototype
    demo; a production deployment would use a longer, documented cadence
    (e.g. hourly/daily cron), not this same short interval.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from api.v1.grievances import run_sla_check

    scheduler = BackgroundScheduler()

    def job():
        session = sessionmaker()
        try:
            escalated = run_escalation_check(session)
            session.commit()
            sla_escalated = run_sla_check(session)
            session.commit()
            if escalated or sla_escalated:
                logger.info(
                    "scheduler tick: %d CAPA escalated, %d grievance(s) SLA-escalated",
                    len(escalated), len(sla_escalated),
                )
        except Exception:
            logger.exception("scheduled escalation/SLA job failed")
            session.rollback()
        finally:
            session.close()

    from app.config import get_settings
    interval = get_settings().scheduler_interval_seconds
    scheduler.add_job(job, "interval", seconds=interval, id="capa_and_grievance_checks")
    scheduler.start()
    return scheduler
