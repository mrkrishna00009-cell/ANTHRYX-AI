"""Bhashini provider.

State of play, stated plainly: no Bhashini call has ever succeeded in this
project's development environment, because the host is not reachable from
it. The client below is written against Bhashini's documented request
shape, but it is UNVERIFIED against the live service.

When credentials are absent the provider does not attempt a call and does
not raise. It returns a result marked BHASHINI_UNAVAILABLE so the caller
can fall back and the interface can say which happened.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.config import Settings, get_settings
from integrations.providers import (
    AsrResult, LanguageProvider, OcrResult, ProviderError, TranslationResult,
)
from models.enums import DataProvenance, ProviderStatus

logger = logging.getLogger(__name__)

#: Languages this project is prepared to route to Bhashini. Whether a given
#: pipeline actually serves one is a deployment question; the list is not a
#: claim of support.
CONFIGURED_LANGUAGES: tuple[str, ...] = ("hi", "bn", "te", "or", "en")

LANGUAGE_LABELS = {
    "hi": "Hindi", "bn": "Bengali", "te": "Telugu",
    "or": "Odia", "en": "English",
}

UNAVAILABLE_DETAIL = (
    "Bhashini credentials are not configured. No request was sent. "
    "Set BHASHINI_USER_ID, BHASHINI_API_KEY, BHASHINI_INFERENCE_API_KEY and "
    "BHASHINI_PIPELINE_URL in .env to enable the live provider."
)


class BhashiniProvider(LanguageProvider):
    name = "bhashini"

    def __init__(self, settings: Settings | None = None, session: Any = None):
        self.settings = settings or get_settings()
        self._session = session or requests

    def is_configured(self) -> bool:
        s = self.settings
        return bool(
            s.bhashini_user_id and s.bhashini_api_key
            and s.bhashini_inference_api_key and s.bhashini_pipeline_url
        )

    # --- transport ----------------------------------------------------
    def _post(self, payload: dict) -> dict:
        s = self.settings
        headers = {
            "Content-Type": "application/json",
            "userID": s.bhashini_user_id or "",
            "ulcaApiKey": s.bhashini_api_key or "",
            "Authorization": s.bhashini_inference_api_key or "",
        }
        last: Exception | None = None
        for attempt in range(s.bhashini_max_retries + 1):
            try:
                response = self._session.post(
                    s.bhashini_pipeline_url, json=payload,
                    headers=headers, timeout=s.bhashini_timeout_seconds,
                )
                if response.status_code >= 500 and attempt < s.bhashini_max_retries:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise ProviderError(
                        f"Bhashini returned {response.status_code}: {response.text[:200]}"
                    )
                return response.json()
            except requests.RequestException as exc:
                last = exc
                if attempt < s.bhashini_max_retries:
                    time.sleep(0.2 * (attempt + 1))
                    continue
        raise ProviderError(f"Bhashini transport failure: {last}")

    def _unavailable_ocr(self) -> OcrResult:
        return OcrResult(
            text="", confidence=None,
            status=ProviderStatus.BHASHINI_UNAVAILABLE,
            provenance=DataProvenance.LIVE_EXTERNAL_API,
            engine=self.name, detail=UNAVAILABLE_DETAIL,
        )

    # --- operations ---------------------------------------------------
    def ocr(self, image_bytes: bytes, language_hint: str | None = None) -> OcrResult:
        if not self.is_configured():
            return self._unavailable_ocr()
        body = self._post({
            "pipelineTasks": [{
                "taskType": "ocr",
                "config": {"language": {"sourceLanguage": language_hint or "hi"}},
            }],
            "inputData": {"image": [{"imageContent": image_bytes.decode("latin-1")}]},
        })
        text, confidence = _extract_text(body)
        return OcrResult(
            text=text, confidence=confidence,
            status=ProviderStatus.LIVE_BHASHINI,
            provenance=DataProvenance.LIVE_EXTERNAL_API,
            engine=self.name, raw=body,
        )

    def asr(self, audio_bytes: bytes, source_language: str) -> AsrResult:
        if not self.is_configured():
            return AsrResult(
                transcript="", source_language=source_language,
                status=ProviderStatus.BHASHINI_UNAVAILABLE,
                provenance=DataProvenance.LIVE_EXTERNAL_API,
                detail=UNAVAILABLE_DETAIL,
            )
        body = self._post({
            "pipelineTasks": [{
                "taskType": "asr",
                "config": {"language": {"sourceLanguage": source_language}},
            }],
            "inputData": {"audio": [{"audioContent": audio_bytes.decode("latin-1")}]},
        })
        text, confidence = _extract_text(body)
        return AsrResult(
            transcript=text, source_language=source_language,
            status=ProviderStatus.LIVE_BHASHINI,
            provenance=DataProvenance.LIVE_EXTERNAL_API,
            confidence=confidence,
        )

    def translate(
        self, text: str, source_language: str, target_language: str = "en"
    ) -> TranslationResult:
        if not self.is_configured():
            return TranslationResult(
                text="", source_language=source_language,
                target_language=target_language,
                status=ProviderStatus.BHASHINI_UNAVAILABLE,
                provenance=DataProvenance.LIVE_EXTERNAL_API,
                detail=UNAVAILABLE_DETAIL,
            )
        body = self._post({
            "pipelineTasks": [{
                "taskType": "translation",
                "config": {"language": {
                    "sourceLanguage": source_language,
                    "targetLanguage": target_language,
                }},
            }],
            "inputData": {"input": [{"source": text}]},
        })
        translated, _ = _extract_text(body)
        return TranslationResult(
            text=translated, source_language=source_language,
            target_language=target_language,
            status=ProviderStatus.LIVE_BHASHINI,
            provenance=DataProvenance.LIVE_EXTERNAL_API,
        )


def _extract_text(body: dict) -> tuple[str, float | None]:
    """Pull text out of a pipeline response without assuming one shape."""
    for key in ("pipelineResponse", "output", "data"):
        section = body.get(key)
        if isinstance(section, list) and section:
            first = section[0]
            if isinstance(first, dict):
                out = first.get("output")
                if isinstance(out, list) and out and isinstance(out[0], dict):
                    return (
                        out[0].get("source") or out[0].get("target", ""),
                        out[0].get("confidence"),
                    )
                if isinstance(out, str):
                    return out, None
    return "", None
