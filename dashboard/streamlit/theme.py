"""Design tokens for the ANTHRYX AI dashboard - light and dark themes.

Direction (locked): professional institutional in both modes. Light is
white/light-grey surfaces with a navy accent. Dark is a dark neutral
surface (not pure black) with the same navy/teal accent family, never a
neon/gaming palette. Risk colours are semantic only, never brand colour,
and are chosen per-theme only for contrast - the same hue identity
(green=low, amber=medium, orange=high, red=critical) is preserved in
both so the meaning never shifts with the toggle.

FONT_UI/FONT_MONO/RADIUS_PX/DENSITY_ROW_HEIGHT_PX are theme-independent
layout tokens, unchanged from the original single-theme module.
"""

from __future__ import annotations

FONT_UI = "'IBM Plex Sans', 'Segoe UI', 'Helvetica Neue', Arial, system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', 'Cascadia Code', 'SFMono-Regular', Consolas, monospace"

RADIUS_PX = 3
DENSITY_ROW_HEIGHT_PX = 34

LIGHT = {
    "SURFACE": "#FFFFFF",
    "SURFACE_SUNKEN": "#F4F6F8",
    "BORDER": "#D7DDE3",
    "TEXT": "#141A1F",
    "TEXT_MUTED": "#5A6673",
    "ACCENT": "#14365C",
    "ACCENT_HOVER": "#0E2742",
    "RISK": {
        "LOW": "#1E7A45", "MEDIUM": "#B3730B", "HIGH": "#C2410C", "CRITICAL": "#9B1C1C",
    },
}

DARK = {
    "SURFACE": "#1B2226",
    "SURFACE_SUNKEN": "#141A1E",
    "BORDER": "#3A444B",
    "TEXT": "#E8ECEF",
    "TEXT_MUTED": "#A9B4BD",
    "ACCENT": "#5B9BD5",
    "ACCENT_HOVER": "#7FB3E0",
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
