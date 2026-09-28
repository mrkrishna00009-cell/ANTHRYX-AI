"""MSHA open-data column contract for the M3 supervised risk model.

Every column named here was taken from MSHA's own published definition
files for the corresponding dataset. None was guessed. Nothing in this
module reads or fabricates data; it declares what the ingestion adapter
expects so the adapter can be written and tested before the archives are
supplied, and so a mismatch is reported loudly rather than papered over.

Required archives (five of MSHA's twenty):
    Mines.zip, Inspections.zip, Violations.zip, Accidents.zip,
    MinesProdYearly.zip

The remaining fifteen are not needed. Assessed Violations is redundant
because Violations already carries PROPOSED_PENALTY; the sampling datasets
are industrial hygiene rather than enforcement; Mine Addresses of Record
is explicitly not the mine's location, so MINES.LATITUDE/LONGITUDE is used
instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Files are pipe-delimited text inside each archive.
DELIMITER = "|"


@dataclass(frozen=True)
class DatasetContract:
    name: str
    archive: str
    key: str
    required_columns: tuple[str, ...]
    purpose: str
    optional_columns: tuple[str, ...] = field(default_factory=tuple)


MINES = DatasetContract(
    name="mines", archive="Mines.zip", key="MINE_ID",
    required_columns=(
        "MINE_ID", "CURRENT_MINE_NAME", "COAL_METAL_IND", "CURRENT_MINE_TYPE",
        "CURRENT_MINE_STATUS", "STATE",
    ),
    optional_columns=(
        "CURRENT_STATUS_DT", "CURRENT_CONTROLLER_ID", "NO_EMPLOYEES",
        "LATITUDE", "LONGITUDE", "PRIMARY_CANVASS",
    ),
    purpose="Mine master record and scope selection.",
)

INSPECTIONS = DatasetContract(
    name="inspections", archive="Inspections.zip", key="EVENT_NO",
    required_columns=(
        "EVENT_NO", "MINE_ID", "INSPECTION_BEGIN_DT", "CAL_YR",
    ),
    optional_columns=(
        "INSPECTION_END_DT", "ACTIVITY_CODE", "ACTIVITY", "NBR_INSPECTORS",
        "TOTAL_ON_SITE_HOURS", "TOTAL_INSP_HOURS",
        "TOTAL_INSP_HRS_SPVR_TRAINEE", "COAL_METAL_IND",
    ),
    purpose="Inspection recency and effort features.",
)

VIOLATIONS = DatasetContract(
    name="violations", archive="Violations.zip", key="VIOLATION_NO",
    required_columns=(
        "VIOLATION_NO", "EVENT_NO", "MINE_ID", "VIOLATION_ISSUE_DT",
        "SIG_SUB", "PART_SECTION", "CAL_YR",
    ),
    optional_columns=(
        "VIOLATION_OCCUR_DT", "MINE_TYPE", "COAL_METAL_IND", "CIT_ORD_SAFE",
        "LIKELIHOOD", "INJ_ILLNESS", "NEGLIGENCE", "NO_AFFECTED",
        "PROPOSED_PENALTY", "VIOLATOR_TYPE_CD", "CONTRACTOR_ID",
    ),
    purpose="Violation counts, S&S counts, repeat ratio, penalty features.",
)

ACCIDENTS = DatasetContract(
    name="accidents", archive="Accidents.zip", key="DOCUMENT_NO",
    required_columns=(
        "DOCUMENT_NO", "MINE_ID", "ACCIDENT_DT", "DEGREE_INJURY_CD", "CAL_YR",
    ),
    optional_columns=(
        "DEGREE_INJURY", "NO_INJURIES", "DAYS_LOST", "SUBUNIT_CD",
        "CLASSIFICATION", "ACCIDENT_TYPE", "IMMED_NOTIFY", "CONTRACTOR_ID",
        "COAL_METAL_IND",
    ),
    purpose="Supplies the supervised label.",
)

ANNUAL_EMPLOY_PROD = DatasetContract(
    name="annual_employ_prod", archive="MinesProdYearly.zip", key="MINE_ID",
    required_columns=("MINE_ID", "CAL_YR"),
    optional_columns=(
        "SUBUNIT_CD", "ANNUAL_HOURS", "ANNUAL_COAL_PRODUCTION",
        "AVG_EMPLOYEE_CNT", "COAL_METAL_IND",
    ),
    purpose="Mine size and exposure hours per year.",
)

REQUIRED_DATASETS: tuple[DatasetContract, ...] = (
    MINES, INSPECTIONS, VIOLATIONS, ACCIDENTS, ANNUAL_EMPLOY_PROD,
)


# --- locked label definition ------------------------------------------
#: Lost-time-or-worse. Fatality; permanent total or partial disability;
#: days away from work only; days away plus restricted activity.
LABEL_DEGREE_INJURY_CODES: frozenset[str] = frozenset({"01", "02", "03", "04"})

#: Excluded: accident only; natural causes; non-employees; first aid and
#: all other cases.
EXCLUDED_DEGREE_INJURY_CODES: frozenset[str] = frozenset({"00", "08", "09", "10"})

#: Accidents to a contractor's employee at the mine COUNT toward the label.
#: They are accidents at that mine and reflect its actual safety outcome.
#: Recorded explicitly because the choice changes the positive rate.
INCLUDE_CONTRACTOR_ACCIDENTS: bool = True


# --- locked windowing -------------------------------------------------
@dataclass(frozen=True)
class WindowPolicy:
    """Features look back; the label looks forward; they never overlap."""

    feature_lookback_days: int = 365
    label_horizon_days: int = 365
    #: Annual, non-overlapping. One row per (MINE_ID, window_end_date).
    stride_days: int = 365
    #: Backdating during a post-accident investigation can push an
    #: occurrence date before the accident it resulted from. Keying on the
    #: issue date keeps the outcome out of the features.
    violation_date_column: str = "VIOLATION_ISSUE_DT"
    shadow_date_column: str = "VIOLATION_OCCUR_DT"
    #: Rows where the two dates straddle the cutoff are counted and
    #: reported so the size of the effect is auditable.
    audit_straddling_violation_dates: bool = True
    #: CURRENT_MINE_STATUS is a present-day snapshot. Filtering training
    #: windows on it drops mines abandoned after a serious accident and
    #: biases the label. It may only narrow the demo scoring population.
    filter_training_on_current_status: bool = False


WINDOW_POLICY = WindowPolicy()

#: Feature columns of the training table, in order.
FEATURE_COLUMNS: tuple[str, ...] = (
    "violations_last_12m",
    "ss_violations_last_12m",
    "repeat_violation_ratio",
    "days_since_last_inspection",
    "inspection_hours_last_12m",
    "avg_penalty_amount",
    "mine_size_avg_employees",
    "production_hours",
    "mine_type",
)

LABEL_COLUMN = "label_accident_next_12m"
KEY_COLUMNS: tuple[str, ...] = ("mine_id", "window_end_dt")


def missing_columns(contract: DatasetContract, present: list[str]) -> list[str]:
    """Which required columns a supplied file does not have."""
    upper = {c.strip().upper() for c in present}
    return [c for c in contract.required_columns if c not in upper]


def contract_summary() -> dict:
    return {
        "required_archives": [c.archive for c in REQUIRED_DATASETS],
        "delimiter": DELIMITER,
        "label_degree_injury_codes": sorted(LABEL_DEGREE_INJURY_CODES),
        "excluded_degree_injury_codes": sorted(EXCLUDED_DEGREE_INJURY_CODES),
        "include_contractor_accidents": INCLUDE_CONTRACTOR_ACCIDENTS,
        "violation_date_column": WINDOW_POLICY.violation_date_column,
        "stride": "annual, non-overlapping",
        "filter_training_on_current_status": (
            WINDOW_POLICY.filter_training_on_current_status
        ),
        "feature_columns": list(FEATURE_COLUMNS),
        "label_column": LABEL_COLUMN,
        "raw_archives_bundled": False,
        "note": (
            "This describes the CONTRACT for the five raw MSHA archives "
            "(Mines/Inspections/Violations/Accidents/MinesProdYearly) - "
            "column names are taken from MSHA's published definition "
            "files. The raw archives themselves are NOT bundled with "
            "this repository or its final package ('raw_archives_bundled: "
            "false' above refers only to that). This is a separate fact "
            "from whether a model has been trained: it has. A real, "
            "frozen M3 model (artifacts/accident_risk_model.joblib) was "
            "trained on real MSHA data matching this exact contract, "
            "under a strict temporal train/validation/test split; its "
            "measured performance figures live in "
            "artifacts/accident_risk_model_metrics.json and are also "
            "returned by GET /risk/model-status alongside this contract. "
            "Do not read 'raw archives not bundled' as 'no model exists' "
            "- the frozen artifact and the raw training data are two "
            "different things with two different bundling answers."
        ),
    }
