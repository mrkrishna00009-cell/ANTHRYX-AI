"""M1 - OCR extraction pipeline.

Locked policy, implemented exactly:

    Tesseract (primary, local, free)
        -> mean confidence check against a configurable threshold
        -> Bhashini OCR (fallback), via the existing provider abstraction
        -> structured field extraction
        -> human verification (unchanged, downstream of this module)

Tesseract is never asked to guess at a result it does not have; an empty
or unreadable image yields empty text and 0 confidence, which correctly
triggers the fallback path rather than being silently accepted.

The fallback is invoked only when Tesseract's confidence is below
threshold OR the detected script is non-Latin (Devanagari and other
Indic scripts are exactly where Tesseract's Indic language packs are
weakest). No OCR output is ever fabricated for either engine.
"""
from __future__ import annotations

import io

import pytesseract
from PIL import Image

from app.config import Settings, get_settings
from integrations.factory import select_language_provider
from integrations.providers import OcrResult
from models.enums import OcrEngine, ProviderStatus


def _mean_confidence(image: Image.Image) -> tuple[str, float | None]:
    """Runs Tesseract with per-word confidence data. Returns (text, mean
    confidence in [0,100], or None if no words were recognised at all -
    never a fabricated confidence for an empty result)."""
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words, confidences = [], []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        conf = float(conf)
        if text and conf >= 0:
            words.append(text)
            confidences.append(conf)
    joined = " ".join(words)
    mean_conf = round(sum(confidences) / len(confidences), 2) if confidences else None
    return joined, mean_conf


def _looks_non_latin(text: str) -> bool:
    """A crude, honest signal: any character outside the Latin block that
    Tesseract's eng model did manage to recognise suggests a mixed-script
    document Tesseract is likely to be weak on overall."""
    return any(ord(ch) > 0x0900 for ch in text)  # Devanagari and beyond starts at U+0900


def run_ocr(image_bytes: bytes, settings: Settings | None = None) -> OcrResult:
    """The locked pipeline. Returns exactly one OcrResult - the one that
    is actually used - with `engine` and `status` telling the caller
    which path was taken. Never silently blends the two."""
    settings = settings or get_settings()
    threshold = settings.ocr_confidence_threshold

    try:
        image = Image.open(io.BytesIO(image_bytes))
        text, confidence = _mean_confidence(image)
    except Exception:  # corrupt/unreadable image - never fabricate a result
        text, confidence = "", None

    tesseract_ok = (
        confidence is not None
        and confidence >= threshold
        and not _looks_non_latin(text)
    )
    if tesseract_ok:
        from models.enums import DataProvenance
        return OcrResult(
            text=text, confidence=confidence / 100.0,
            status=ProviderStatus.TESSERACT_LOCAL, provenance=DataProvenance.REAL_PUBLIC_DATA,
            engine=OcrEngine.TESSERACT.value,
            detail="Tesseract confidence met the configured threshold; no fallback invoked.",
        )

    # Fallback: Bhashini if configured, otherwise the demo fallback -
    # exactly the existing provider-selection abstraction, never bypassed.
    # A real Bhashini failure (timeout, 5xx after retries, network error)
    # must degrade to an honest BHASHINI_UNAVAILABLE result, never an
    # unhandled 500 - this is the actual "failed request -> safe fallback"
    # contract, not merely documented.
    import dataclasses
    from integrations.providers import ProviderError
    from models.enums import DataProvenance

    selection = select_language_provider(settings)
    try:
        fallback_result = selection.provider.ocr(image_bytes, language_hint=None)
    except ProviderError as exc:
        return OcrResult(
            text="", confidence=None, status=ProviderStatus.BHASHINI_UNAVAILABLE,
            provenance=DataProvenance.LIVE_EXTERNAL_API, engine=selection.provider.name,
            detail=(
                f"Tesseract confidence {confidence}{'%' if confidence is not None else ' (no text recognised)'} "
                f"was below threshold {threshold}%. Bhashini fallback was attempted but the live "
                f"request failed ({exc}); no fabricated result is returned."
            ),
        )
    return dataclasses.replace(
        fallback_result,
        detail=(
            f"Tesseract confidence {confidence}{'%' if confidence is not None else ' (no text recognised)'} "
            f"was below threshold {threshold}% or a non-Latin script was suspected "
            f"(tesseract text preview: {text[:60]!r}). Fell back to {selection.provider.name}. "
            + (fallback_result.detail or "")
        ),
    )
