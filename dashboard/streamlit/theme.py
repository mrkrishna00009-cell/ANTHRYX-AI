"""Design tokens for the ANTHRYX AI dashboard - light and dark themes.

The visual language is an editorial field instrument: mineral neutrals,
cut-metal edges, and a restrained oxidised-orange signal colour. Risk
colours remain semantic only, never brand colour, and preserve the same
hue identity (green=low, amber=medium, orange=high, red=critical) in
both themes so their meaning never shifts with the toggle.

FONT_UI/FONT_MONO/RADIUS_PX/DENSITY_ROW_HEIGHT_PX are theme-independent
layout tokens, unchanged from the original single-theme module.
"""

from __future__ import annotations

FONT_UI = "'IBM Plex Sans', 'Segoe UI', 'Helvetica Neue', Arial, system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', 'Cascadia Code', 'SFMono-Regular', Consolas, monospace"

RADIUS_PX = 3
DENSITY_ROW_HEIGHT_PX = 34

LIGHT = {
    "SURFACE": "#F8F7F1",
    "SURFACE_SUNKEN": "#ECEAE1",
    "BORDER": "#CFCBBE",
    "TEXT": "#18231F",
    "TEXT_MUTED": "#626D65",
    "ACCENT": "#C84D2C",
    "ACCENT_HOVER": "#A63B20",
    "RISK": {
        "LOW": "#1E7A45", "MEDIUM": "#B3730B", "HIGH": "#C2410C", "CRITICAL": "#9B1C1C",
    },
}

DARK = {
    "SURFACE": "#111A17",
    "SURFACE_SUNKEN": "#19231F",
    "BORDER": "#35453C",
    "TEXT": "#E8EADF",
    "TEXT_MUTED": "#A5B0A7",
    "ACCENT": "#F07A4A",
    "ACCENT_HOVER": "#FF9A70",
    "RISK": {
        "LOW": "#4CAF7D", "MEDIUM": "#D99A3D", "HIGH": "#E0703F", "CRITICAL": "#E05A5A",
    },
}

THEMES = {"light": LIGHT, "dark": DARK}


def get_theme(mode: str) -> dict:
    return THEMES.get(mode, LIGHT)


def risk_color(level: str, mode: str = "light") -> str:
    theme = get_theme(mode)
    return theme["RISK"].get(level.upper(), theme["TEXT_MUTED"])


SURFACE = LIGHT["SURFACE"]
SURFACE_SUNKEN = LIGHT["SURFACE_SUNKEN"]
BORDER = LIGHT["BORDER"]
TEXT = LIGHT["TEXT"]
TEXT_MUTED = LIGHT["TEXT_MUTED"]
ACCENT = LIGHT["ACCENT"]
ACCENT_HOVER = LIGHT["ACCENT_HOVER"]
RISK = LIGHT["RISK"]
