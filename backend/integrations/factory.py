"""Chooses the language provider and reports which one is in play."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from integrations.bhashini import CONFIGURED_LANGUAGES, BhashiniProvider
from integrations.demo_fallback import DemoFallbackProvider
from integrations.providers import LanguageProvider
from models.enums import ProviderStatus


@dataclass(frozen=True)
class ProviderSelection:
    provider: LanguageProvider
    status: ProviderStatus
    configured_languages: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict:
        return {
            "provider": self.provider.name,
            "status": self.status.value,
            "configured_languages": list(self.configured_languages),
            "detail": self.detail,
        }


def select_language_provider(settings: Settings | None = None) -> ProviderSelection:
    settings = settings or get_settings()
    bhashini = BhashiniProvider(settings)
    if bhashini.is_configured():
        return ProviderSelection(
            provider=bhashini,
            status=ProviderStatus.LIVE_BHASHINI,
            configured_languages=CONFIGURED_LANGUAGES,
            detail=(
                "Bhashini credentials present. Live calls will be attempted. "
                "Whether a given language is served depends on the configured "
                "pipeline; this list is a routing configuration, not a "
                "guarantee of support."
            ),
        )
    return ProviderSelection(
        provider=DemoFallbackProvider(),
        status=ProviderStatus.BHASHINI_UNAVAILABLE,
        configured_languages=CONFIGURED_LANGUAGES,
        detail=(
            "Bhashini credentials are absent, so the demo fallback is active. "
            "It performs no recognition and every result it returns is marked "
            "DEMO_FALLBACK. No output from it may be presented as a Bhashini "
            "result."
        ),
    )
