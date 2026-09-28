"""Demo fallback provider.

This exists so the system keeps working without Bhashini credentials. It
performs no recognition of any kind.

It does not guess at the contents of an image or an audio clip, because a
plausible invented transcript shown next to a real one is worse than no
transcript. Every result it returns is marked DEMO_FALLBACK, and callers
must surface that label in the interface.
"""

from __future__ import annotations

import hashlib

from integrations.providers import (
    AsrResult, LanguageProvider, OcrResult, TranslationResult,
)
from models.enums import DataProvenance, ProviderStatus

DEMO_NOTICE = (
    "DEMO FALLBACK - no language service was called. This output was not "
    "produced by Bhashini or by any recognition engine."
)


class DemoFallbackProvider(LanguageProvider):
    name = "demo-fallback"

    def is_configured(self) -> bool:
        # Always usable, and always honest about what it is.
        return True

    def _tag(self, payload: bytes | str) -> str:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        return hashlib.sha256(data).hexdigest()[:12]

    def ocr(self, image_bytes: bytes, language_hint: str | None = None) -> OcrResult:
        return OcrResult(
            text="",
            confidence=None,
            status=ProviderStatus.DEMO_FALLBACK,
            provenance=DataProvenance.DEMO_FALLBACK,
            engine=self.name,
            detail=(
                f"{DEMO_NOTICE} Image received "
                f"({len(image_bytes)} bytes, sha256:{self._tag(image_bytes)}) "
                "but not processed. Configure Bhashini or rely on Tesseract."
            ),
        )

    def asr(self, audio_bytes: bytes, source_language: str) -> AsrResult:
        return AsrResult(
            transcript="",
            source_language=source_language,
            status=ProviderStatus.DEMO_FALLBACK,
            provenance=DataProvenance.DEMO_FALLBACK,
            confidence=None,
            detail=(
                f"{DEMO_NOTICE} Audio received "
                f"({len(audio_bytes)} bytes, sha256:{self._tag(audio_bytes)}) "
                "and stored as evidence, but not transcribed."
            ),
        )

    def translate(
        self, text: str, source_language: str, target_language: str = "en"
    ) -> TranslationResult:
        return TranslationResult(
            text="",
            source_language=source_language,
            target_language=target_language,
            status=ProviderStatus.DEMO_FALLBACK,
            provenance=DataProvenance.DEMO_FALLBACK,
            detail=f"{DEMO_NOTICE} Source text preserved; no translation performed.",
        )
