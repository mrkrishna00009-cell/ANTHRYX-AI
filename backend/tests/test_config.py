"""Configuration must come from the environment, never from hardcoded secrets."""

from __future__ import annotations

from app.config import Settings


def test_settings_load_without_any_credentials():
    settings = Settings()
    assert settings.app_name == "ANTHRYX AI"
    assert settings.jwt_secret is None or isinstance(settings.jwt_secret, str)


def test_bhashini_credentials_default_to_absent():
    """Absent credentials are a supported state, not a crash."""
    settings = Settings()
    assert settings.bhashini_api_key is None or isinstance(settings.bhashini_api_key, str)
    assert settings.bhashini_timeout_seconds > 0
    assert settings.bhashini_max_retries >= 0


def test_cors_origins_parse_to_list():
    settings = Settings(cors_allow_origins="http://a.test, http://b.test")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_ocr_threshold_present_for_m1_fallback_decision():
    settings = Settings()
    assert 0 < settings.ocr_confidence_threshold <= 100
