"""M3 - live feature construction from application data.

Builds the deployable feature vector for a mine from THIS APPLICATION's
own tables - never from MSHA rows, never from Q679/Q181, never from a
synthetic CSV, never a hard-coded value. Where no Indian-application
concept genuinely exists for an MSHA-shaped feature, the feature is left
NULL and the reason is recorded - it is never invented.

Mapping (documented once, here, as the single source of truth):

FEATURE                     | SOURCE TABLE / FIELD                          | WINDOW              | TRANSFORMATION                                                  | NULL POLICY                              | PROVENANCE
violations_last_12m         | inspection_findings.compliant (=False)        | trailing 365 days    | COUNT of non-compliant findings, joined via field_evidence      | 0 if inspected with none non-compliant   | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
                             | joined to field_evidence(kind=INSPECTION)     |                      |                                                                  | (an observed zero, not missing)          |
ss_violations_last_12m      | inspection_findings.severity IN (HIGH,CRIT)   | trailing 365 days    | COUNT of the above subset with elevated severity                | 0 if any non-compliant findings exist    | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
repeat_violation_ratio      | inspection_findings.rule_id                   | trailing 365 days    | 1 - (COUNT DISTINCT rule_id / COUNT non-compliant findings)     | NULL if zero non-compliant findings      | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
                             |                                                |                      | among non-compliant findings only                               | (ratio undefined, never 0)               |
days_since_last_inspection  | field_evidence.server_timestamp               | all history          | as_of_date - MAX(server_timestamp) where kind=INSPECTION        | NULL if never inspected                  | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
inspection_hours_last_12m   | NO SOURCE EXISTS                              | n/a                  | n/a                                                              | ALWAYS NULL                              | UNAVAILABLE - no duration/hours field exists anywhere in the Indian schema; never approximated
mine_size_avg_employees     | mines.average_employee_count                  | current value        | direct read                                                     | NULL if not set on the mine              | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
mine_type                   | mines.mine_type                               | current value        | UNDERGROUND->UNDERGROUND, OPENCAST->OPENCAST, MIXED unmapped    | unmapped if MIXED (no MSHA-side target)  | USER_SUPPLIED (aggregated from real inspection/field-evidence records)
production_hours            | (mines.production_hours_last_year EXISTS      | -                    | NEVER READ for this purpose                                     | ALWAYS NaN, unconditionally              | BLOCKED_FOR_INDIAN_INFERENCE
                             |  but is deliberately never used here)          |                      |                                                                  |                                           |
avg_penalty_amount          | NO SOURCE EXISTS                              | -                    | n/a                                                              | ALWAYS NaN, unconditionally              | BLOCKED_FOR_INDIAN_INFERENCE

The two BLOCKED features are never read from any column, even where a
column happens to exist (``production_hours_last_year``) - the blocking
policy is about what M3 is permitted to use for Indian inference, not
about whether a number could technically be captured.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.enums import DataProvenance, EvidenceKind, Severity
from models.field_evidence import FieldEvidence, InspectionFinding
from models.ml import MlFeature
from models.organisation import Mine

WINDOW_DAYS = 365

FEATURE_PROVENANCE_UNAVAILABLE = "inspection_hours_last_12m has no source field in this application"


@dataclass(frozen=True)
class FeatureAvailability:
    """What was actually available when the vector was built - never
    silently dropped, always reported alongside the persisted row."""
    violations_last_12m_observed: bool
    mine_size_available: bool
    mine_type_mapped: bool
    ever_inspected: bool
    notes: list[str]
    rescore_was_required: bool = False


class FeatureBuilder:
    def __init__(self, session: Session):
        self.session = session

    def build(self, mine_id, as_of: date | None = None) -> tuple[MlFeature, FeatureAvailability]:
        """Builds (and persists) the deployable MlFeature row for a mine as
        of a given date (default: today, UTC). Idempotent: calling this
        again for the same (mine_id, window_end_date) UPDATES the existing
        row in place rather than creating a duplicate - the unique
        constraint on (mine_id, window_end_date) is the real mechanism,
        not a pre-check that could race."""
        as_of = as_of or datetime.now(timezone.utc).date()
        window_start_dt = datetime.combine(as_of - timedelta(days=WINDOW_DAYS), datetime.min.time(), timezone.utc)
        window_end_dt = datetime.combine(as_of, datetime.max.time(), timezone.utc)

        mine = self.session.get(Mine, mine_id)
        if mine is None:
            raise ValueError(f"Mine {mine_id} not found")

        notes: list[str] = []

        # --- inspection-derived features -----------------------------
        findings = self.session.execute(
            select(InspectionFinding, FieldEvidence.server_timestamp)
            .join(FieldEvidence, FieldEvidence.id == InspectionFinding.evidence_id)
            .where(
                FieldEvidence.mine_id == mine_id,
                FieldEvidence.kind == EvidenceKind.INSPECTION,
                FieldEvidence.server_timestamp >= window_start_dt,
                FieldEvidence.server_timestamp <= window_end_dt,
            )
        ).all()

        non_compliant = [(f, ts) for f, ts in findings if f.compliant is False]
        violations_last_12m = len(non_compliant)
        ss_violations_last_12m = sum(
            1 for f, _ in non_compliant if f.severity in (Severity.HIGH, Severity.CRITICAL)
        )
        distinct_rules = len({f.rule_id for f, _ in non_compliant if f.rule_id is not None})
        if violations_last_12m == 0:
            repeat_violation_ratio = None
            notes.append("repeat_violation_ratio: NULL - no non-compliant findings in window, ratio undefined")
        else:
            repeat_violation_ratio = round(1 - (distinct_rules / violations_last_12m), 6)

        # --- days since last inspection (all history, not window-limited)
        last_inspection_ts = self.session.execute(
            select(FieldEvidence.server_timestamp)
            .where(FieldEvidence.mine_id == mine_id, FieldEvidence.kind == EvidenceKind.INSPECTION)
            .order_by(FieldEvidence.server_timestamp.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_inspection_ts is None:
            days_since_last_inspection = None
            notes.append("days_since_last_inspection: NULL - mine has never been inspected")
        else:
            days_since_last_inspection = (window_end_dt.date() - last_inspection_ts.date()).days

        # --- inspection_hours_last_12m: genuinely unavailable ---------
        inspection_hours_last_12m = None
        notes.append(f"inspection_hours_last_12m: NULL - {FEATURE_PROVENANCE_UNAVAILABLE}")

        # --- mine_size_avg_employees -----------------------------------
        mine_size_avg_employees = (
            float(mine.average_employee_count) if mine.average_employee_count is not None else None
        )
        if mine_size_avg_employees is None:
            notes.append("mine_size_avg_employees: NULL - not set on this mine record")

        # --- mine_type ---------------------------------------------------
        mine_type_map = {"UNDERGROUND": "UNDERGROUND", "OPENCAST": "OPENCAST"}
        mine_type = mine_type_map.get(mine.mine_type.value)
        if mine_type is None:
            notes.append(f"mine_type: unmapped MSHA-side value for {mine.mine_type.value} (MIXED has no MSHA target)")

        # --- blocked features: never read, unconditionally NaN -------
        # production_hours and avg_penalty_amount are intentionally never
        # populated from mines.production_hours_last_year or anywhere else.

        existing = self.session.execute(
            select(MlFeature).where(MlFeature.mine_id == mine_id, MlFeature.window_end_date == as_of)
        ).scalar_one_or_none()

        if existing is not None:
            row = existing
        else:
            row = MlFeature(mine_id=mine_id, window_end_date=as_of)
            self.session.add(row)

        row.violations_last_12m = violations_last_12m
        row.ss_violations_last_12m = ss_violations_last_12m
        row.repeat_violation_ratio = repeat_violation_ratio
        row.days_since_last_inspection = days_since_last_inspection
        row.inspection_hours_last_12m = inspection_hours_last_12m
        row.mine_size_avg_employees = mine_size_avg_employees
        row.production_hours = None  # BLOCKED, unconditionally
        row.avg_penalty_amount = None  # BLOCKED, unconditionally
        row.mine_type = mine_type
        row.provenance = DataProvenance.USER_SUPPLIED

        # Clearing this here, not before, is deliberate: the flag means
        # "re-evaluate this mine," and re-evaluation is exactly what a
        # completed build() call is. A build that raises before this line
        # leaves the flag set, which is the correct, honest outcome.
        was_rescore_required = bool(mine.rescore_required)
        mine.rescore_required = False

        self.session.flush()

        availability = FeatureAvailability(
            violations_last_12m_observed=len(findings) > 0,
            mine_size_available=mine_size_avg_employees is not None,
            mine_type_mapped=mine_type is not None,
            ever_inspected=last_inspection_ts is not None,
            notes=notes,
            rescore_was_required=was_rescore_required,
        )
        return row, availability
