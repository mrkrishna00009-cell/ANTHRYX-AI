"""Provider abstraction for OCR, speech recognition and translation.

Three rules govern every implementation here:

1. A result always carries the status that produced it. A demo-fallback
   transcript is never labelled as a live Bhashini response.
2. Absent credentials are a supported state, not an error. The system
   reports BHASHINI_UNAVAILABLE and continues.
3. No implementation invents plausible-looking output and presents it as
   real recognition.

Bhashini is the configured provider; the interface exists so it can be
replaced without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from models.enums import DataProvenance, ProviderStatus


class ProviderError(RuntimeError):
    """Transport, timeout or protocol failure from a language provider."""


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float | None
    status: ProviderStatus
    provenance: DataProvenance
    engine: str
    detected_script: str | None = None
    detail: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AsrResult:
    transcript: str
    source_language: str
    status: ProviderStatus
    provenance: DataProvenance
    confidence: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class TranslationResult:
    text: str
    source_language: str
    target_language: str
    status: ProviderStatus
    provenance: DataProvenance
    detail: str | None = None


class LanguageProvider(ABC):
    """OCR + ASR + NMT behind one interface."""

    name: str = "abstract"

    @abstractmethod
    def is_configured(self) -> bool:
        """True only when real credentials are present."""

    @abstractmethod
    def ocr(self, image_bytes: bytes, language_hint: str | None = None) -> OcrResult: ...

    @abstractmethod
    def asr(self, audio_bytes: bytes, source_language: str) -> AsrResult: ...

    @abstractmethod
    def translate(
        self, text: str, source_language: str, target_language: str = "en"
    ) -> TranslationResult: ...
