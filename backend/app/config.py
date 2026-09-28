"""Runtime configuration for ANTHRYX AI.

Every value is read from the environment (see .env.example at the repo root).
No secret, credential or connection string is hardcoded here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application -------------------------------------------------
    app_name: str = "ANTHRYX AI"
    environment: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- database ----------------------------------------------------
    # PostgreSQL is the primary database. SQLite is a documented
    # development-only fallback so local work is not blocked when no
    # PostgreSQL server is reachable. It is never the production store.
    database_url: str | None = None
    allow_sqlite_fallback: bool = True
    sqlite_fallback_path: str = "data/anthryx_dev.db"
    db_connect_timeout_seconds: int = 3

    # --- auth --------------------------------------------------------
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # --- login rate limiting ------------------------------------------
    # In-memory, per-process. Keyed by the submitted email regardless of
    # whether that account exists, so the limiter itself never becomes a
    # second channel for account enumeration.
    login_max_failures: int = Field(
        default=5, description="Failed attempts allowed for one email before a temporary lockout."
    )
    login_failure_window_seconds: int = Field(
        default=300, description="Failures older than this are forgotten if no lockout is active."
    )
    login_lockout_seconds: int = Field(
        default=60, description="How long a key stays locked out once the failure limit is hit."
    )

    # --- grievances -----------------------------------------------------
    grievance_sla_days: int = Field(
        default=7, description="Days from filing before a grievance is considered SLA-breached."
    )

    # --- background scheduler (Phase: escalation/SLA automation) --------
    # A real, live background job, not merely a directly-callable function.
    # Short interval is deliberate for a prototype/demo, where a reviewer
    # needs to observe automatic escalation within the session rather than
    # waiting for a production-realistic daily cadence. Disabled during
    # tests (which invoke run_escalation_check/run_sla_check directly and
    # deterministically) so no background thread interferes with them.
    scheduler_enabled: bool = Field(
        default=True, description="Runs the CAPA-escalation and grievance-SLA checks on a live interval."
    )
    scheduler_interval_seconds: int = Field(
        default=30, description="Prototype cadence - production would use a daily/hourly cron instead."
    )

    # --- CORS (the React PWA is a separate origin) -------------------
    cors_allow_origins: str = "http://localhost:5173,http://localhost:4173,http://localhost:8501,http://127.0.0.1:5173,http://127.0.0.1:4173,http://127.0.0.1:8501"

    # --- Bhashini (M1 OCR fallback, M2 voice) ------------------------
    # Absent credentials are a supported state. The provider layer then
    # reports DEMO_FALLBACK and never claims a live Bhashini response.
    bhashini_user_id: str | None = None
    bhashini_api_key: str | None = None
    bhashini_inference_api_key: str | None = None
    bhashini_pipeline_url: str | None = None
    bhashini_timeout_seconds: int = 20
    bhashini_max_retries: int = 2

    # --- OCR ---------------------------------------------------------
    tesseract_cmd: str = "tesseract"
    ocr_confidence_threshold: float = Field(
        default=70.0,
        description="Below this mean confidence, M1 escalates to the Bhashini OCR fallback.",
    )

    # --- upload limits -------------------------------------------------
    # Read fully into memory (no streaming-to-disk path exists), so a cap
    # is a genuine DoS control, not a formality. Chosen generously for a
    # scanned certificate image / a short voice-incident clip, not for
    # arbitrary file transfer.
    max_document_upload_bytes: int = Field(
        default=10 * 1024 * 1024, description="Maximum accepted size for a document/OCR upload."
    )
    max_audio_upload_bytes: int = Field(
        default=25 * 1024 * 1024, description="Maximum accepted size for a voice-incident audio upload."
    )
    allowed_document_content_types: tuple[str, ...] = (
        "image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff",
    )
    allowed_audio_content_types: tuple[str, ...] = (
        "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4",
        "audio/m4a", "audio/ogg", "audio/webm",
    )

    # --- MSHA (M3) ---------------------------------------------------
    msha_raw_dir: str = "data/raw/msha"
    msha_processed_dir: str = "data/processed"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def sqlite_url(self) -> str:
        path = REPO_ROOT / self.sqlite_fallback_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
