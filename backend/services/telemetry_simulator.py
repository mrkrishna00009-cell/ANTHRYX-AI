"""M5 - demo-only SIMULATED telemetry generator.

Produces plausible methane/CO/airflow readings for a demo, using the
SAME generator shapes as the Isolation Forest's own training script
(``m5_train.py``'s ``simulate_normal_operation`` / ``simulate_anomalous_
combination``), so what a demo submits and what the model was trained to
recognise are the same kind of signal - never a coincidence, always
labelled SIMULATED, never claimed as physical sensor data, and never
carrying a fabricated geographic coordinate (it takes a mine_id, not a
location).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SimulatedReading:
    sensor_kind: str
    value: float
    unit: str
    recorded_at: datetime
    provenance: str = "SIMULATED"


def _normal(rng: random.Random) -> tuple[float, float, float]:
    airflow = max(2.0, min(14.0, rng.gauss(8.0, 1.2)))
    methane = max(0.0, min(1.0, 0.35 - 0.015 * (airflow - 8.0) + rng.gauss(0, 0.05)))
    co = max(0.0, min(50.0, 12 - 0.6 * (airflow - 8.0) + rng.gauss(0, 2.0)))
    return methane, co, airflow


def _anomalous(rng: random.Random) -> tuple[float, float, float]:
    airflow = max(1.0, min(8.0, rng.gauss(4.5, 1.0)))
    methane = max(0.2, min(0.95, rng.gauss(0.55, 0.08)))
    co = max(5.0, min(45.0, rng.gauss(18.0, 4.0)))
    return methane, co, airflow


def generate_readings(
    mine_id,
    mode: str = "normal",
    seed: int | None = None,
    as_of: datetime | None = None,
) -> list[SimulatedReading]:
    """mode: 'normal' or 'anomaly'. Deterministic when a seed is given -
    the same seed always produces the same three readings, for a
    reproducible demo. Never generates a geographic coordinate; the
    caller already has the mine_id."""
    if mode not in ("normal", "anomaly"):
        raise ValueError(f"mode must be 'normal' or 'anomaly', got {mode!r}")

    rng = random.Random(seed)
    methane, co, airflow = _anomalous(rng) if mode == "anomaly" else _normal(rng)
    ts = as_of or datetime.now(timezone.utc)

    return [
        SimulatedReading("METHANE", round(methane, 4), "%", ts),
        SimulatedReading("CARBON_MONOXIDE", round(co, 2), "ppm", ts),
        SimulatedReading("AIRFLOW", round(airflow, 3), "m3/s", ts),
    ]
