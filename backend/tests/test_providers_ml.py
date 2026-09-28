"""Bhashini provider behaviour and the ML contract.

No test here requires network access. Bhashini transport is mocked; the
demo fallback is exercised directly.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from integrations.bhashini import BhashiniProvider
from integrations.demo_fallback import DemoFallbackProvider
from integrations.factory import select_language_provider
from ml import registry
from ml.msha import schema as msha
from models.enums import DataProvenance, ModelKind, ModelStatus, ProviderStatus


# --- provider selection -----------------------------------------------
def test_without_credentials_the_fallback_is_selected(monkeypatch):
    from app import config

    for var in (
        "BHASHINI_USER_ID", "BHASHINI_API_KEY",
        "BHASHINI_INFERENCE_API_KEY", "BHASHINI_PIPELINE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    config.get_settings.cache_clear()
    selection = select_language_provider()
    assert selection.status is ProviderStatus.BHASHINI_UNAVAILABLE
    assert selection.provider.name == "demo-fallback"


def test_with_credentials_bhashini_is_selected(monkeypatch):
    from app import config

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_API_KEY", "k")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "i")
    monkeypatch.setenv("BHASHINI_PIPELINE_URL", "https://example.invalid/pipeline")
    config.get_settings.cache_clear()
    selection = select_language_provider()
    assert selection.status is ProviderStatus.LIVE_BHASHINI
    assert selection.provider.name == "bhashini"


# --- the fallback must never impersonate Bhashini ---------------------
def test_fallback_invents_no_transcript():
    result = DemoFallbackProvider().asr(b"audio-bytes", "hi")
    assert result.transcript == ""
    assert result.status is ProviderStatus.DEMO_FALLBACK
    assert result.provenance is DataProvenance.DEMO_FALLBACK


def test_fallback_invents_no_ocr_text():
    result = DemoFallbackProvider().ocr(b"image-bytes")
    assert result.text == ""
    assert result.status is ProviderStatus.DEMO_FALLBACK


def test_fallback_invents_no_translation():
    result = DemoFallbackProvider().translate("कुछ पाठ", "hi", "en")
    assert result.text == ""
    assert result.status is ProviderStatus.DEMO_FALLBACK


def test_fallback_never_labels_itself_bhashini():
    for result in (
        DemoFallbackProvider().asr(b"a", "hi"),
        DemoFallbackProvider().ocr(b"b"),
        DemoFallbackProvider().translate("c", "hi"),
    ):
        assert result.status is not ProviderStatus.LIVE_BHASHINI
        assert "not produced by Bhashini" in (result.detail or "")


# --- Bhashini without credentials does not call out -------------------
def test_unconfigured_bhashini_does_not_send_a_request(monkeypatch):
    from app import config

    for var in (
        "BHASHINI_USER_ID", "BHASHINI_API_KEY",
        "BHASHINI_INFERENCE_API_KEY", "BHASHINI_PIPELINE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    config.get_settings.cache_clear()

    transport = Mock()
    provider = BhashiniProvider(session=transport)
    result = provider.asr(b"audio", "hi")

    transport.post.assert_not_called()
    assert result.status is ProviderStatus.BHASHINI_UNAVAILABLE
    assert result.transcript == ""


def test_configured_bhashini_marks_results_live(monkeypatch):
    from app import config

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_API_KEY", "k")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "i")
    monkeypatch.setenv("BHASHINI_PIPELINE_URL", "https://example.invalid/pipeline")
    config.get_settings.cache_clear()

    response = Mock(status_code=200)
    response.json.return_value = {
        "pipelineResponse": [{"output": [{"source": "गैस रिसाव", "confidence": 0.9}]}]
    }
    transport = Mock()
    transport.post.return_value = response

    result = BhashiniProvider(session=transport).asr(b"audio", "hi")
    transport.post.assert_called_once()
    assert result.status is ProviderStatus.LIVE_BHASHINI
    assert result.transcript == "गैस रिसाव"


def test_bhashini_http_error_raises_rather_than_returning_empty_success(monkeypatch):
    from app import config
    from integrations.providers import ProviderError

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_API_KEY", "k")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "i")
    monkeypatch.setenv("BHASHINI_PIPELINE_URL", "https://example.invalid/pipeline")
    config.get_settings.cache_clear()

    response = Mock(status_code=403, text="forbidden")
    transport = Mock()
    transport.post.return_value = response
    with pytest.raises(ProviderError):
        BhashiniProvider(session=transport).translate("x", "hi")


# --- MSHA contract ----------------------------------------------------
def test_five_archives_required():
    assert [c.archive for c in msha.REQUIRED_DATASETS] == [
        "Mines.zip", "Inspections.zip", "Violations.zip",
        "Accidents.zip", "MinesProdYearly.zip",
    ]


def test_locked_label_definition():
    assert msha.LABEL_DEGREE_INJURY_CODES == {"01", "02", "03", "04"}
    assert msha.EXCLUDED_DEGREE_INJURY_CODES == {"00", "08", "09", "10"}
    assert msha.INCLUDE_CONTRACTOR_ACCIDENTS is True


def test_locked_window_policy():
    policy = msha.WINDOW_POLICY
    assert policy.violation_date_column == "VIOLATION_ISSUE_DT"
    assert policy.shadow_date_column == "VIOLATION_OCCUR_DT"
    assert policy.stride_days == 365
    assert policy.feature_lookback_days == 365
    assert policy.label_horizon_days == 365
    # Survivorship bias guard.
    assert policy.filter_training_on_current_status is False


def test_missing_column_detection():
    missing = msha.missing_columns(msha.ACCIDENTS, ["MINE_ID", "ACCIDENT_DT"])
    assert "DEGREE_INJURY_CD" in missing
    assert msha.missing_columns(
        msha.ACCIDENTS,
        ["document_no", "mine_id", "accident_dt", "degree_injury_cd", "cal_yr"],
    ) == []


def test_contract_distinguishes_raw_archives_from_trained_model():
    """The old version of this test asserted the note said "no model has
    been trained" - which became false the moment M3 was actually
    trained, while remaining true that the raw archives aren't bundled.
    Conflating those two facts in one assertion is exactly the stale-
    documentation bug this test now guards against."""
    summary = msha.contract_summary()
    assert summary["raw_archives_bundled"] is False
    assert "not bundled" in summary["note"]
    assert "no model has been trained" not in summary["note"].lower()
    # the two facts must be distinguishable in the same response, not conflated
    assert "raw archive" in summary["note"].lower()
    assert "frozen" in summary["note"].lower() or "trained" in summary["note"].lower()


def test_no_msha_files_are_bundled():
    from app.config import REPO_ROOT

    raw = REPO_ROOT / "data" / "raw"
    assert [p.name for p in raw.rglob("*") if p.is_file() and p.name != ".gitkeep"] == []


# --- model registry ---------------------------------------------------
def test_both_models_report_trained_after_phase4(monkeypatch):
    """Phase 4: both artifacts are now on disk. Each reports TRAINED with
    its own genuine metrics - never one standing in for the other."""
    for kind in (
        ModelKind.ACCIDENT_RISK_SUPERVISED,
        ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST,
    ):
        info = registry.describe(kind)
        assert info.status is ModelStatus.TRAINED
        assert info.metrics is not None
    m3 = registry.describe(ModelKind.ACCIDENT_RISK_SUPERVISED)
    m5 = registry.describe(ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST)
    assert "roc_auc" in m3.metrics          # M3: supervised classification metric
    assert "roc_auc" not in m5.metrics      # M5: never a supervised metric


def test_m3_and_m5_are_different_artifacts():
    assert (
        registry.ARTIFACT_FILENAMES[ModelKind.ACCIDENT_RISK_SUPERVISED]
        != registry.ARTIFACT_FILENAMES[ModelKind.SENSOR_ANOMALY_ISOLATION_FOREST]
    )


# ---------------------------------------------------------------- P0 GATE: timeout + graceful degradation
def test_bhashini_timeout_retries_then_raises_providererror(monkeypatch):
    """Explicitly requested: timeout handling. A real requests.Timeout must
    be retried up to bhashini_max_retries, then surface as ProviderError -
    never silently swallowed, never a fake success."""
    import requests as requests_module
    from app import config
    from integrations.providers import ProviderError

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_API_KEY", "k")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "i")
    monkeypatch.setenv("BHASHINI_PIPELINE_URL", "https://example.invalid/pipeline")
    config.get_settings.cache_clear()

    transport = Mock()
    transport.post.side_effect = requests_module.exceptions.Timeout("simulated timeout")

    with pytest.raises(ProviderError):
        BhashiniProvider(session=transport).translate("x", "hi", "en")

    settings = config.get_settings()
    # one initial attempt + max_retries retries
    assert transport.post.call_count == settings.bhashini_max_retries + 1


def test_ocr_service_degrades_gracefully_on_live_bhashini_failure(monkeypatch, tmp_path):
    """The real defect found and fixed in this gate: a live Bhashini
    failure after retries must produce an honest BHASHINI_UNAVAILABLE
    OcrResult, not an unhandled exception propagating out of the API."""
    from app import config
    from integrations.providers import ProviderError
    import services.ocr as ocr_module

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_API_KEY", "k")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "i")
    monkeypatch.setenv("BHASHINI_PIPELINE_URL", "https://example.invalid/pipeline")
    config.get_settings.cache_clear()

    class FailingProvider:
        name = "bhashini"
        def ocr(self, *a, **kw):
            raise ProviderError("simulated live failure")

    class Selection:
        provider = FailingProvider()

    monkeypatch.setattr(ocr_module, "select_language_provider", lambda *a, **kw: Selection())

    # A blank image guarantees Tesseract confidence is low, forcing the
    # fallback path to actually run.
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")

    result = ocr_module.run_ocr(buf.getvalue(), settings=config.get_settings().model_copy(update={"ocr_confidence_threshold": 999.0}))
    assert result.status.value == "BHASHINI_UNAVAILABLE"
    assert "no fabricated result" in result.detail
