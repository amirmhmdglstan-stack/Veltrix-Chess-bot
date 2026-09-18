"""theme.py - board colour themes for the Veltrix GUI."""

THEMES = {
    "Classic":    ("#f0d9b5", "#b58863"),
    "Blue Grey":  ("#dee3e6", "#8ca2ad"),
    "Forest":     ("#ffffdd", "#86a666"),
    "Sand":       ("#ffe8c8", "#d7a05b"),
    "Slate":      ("#c8cdd2", "#6f7d8c"),
    "Rosewood":   ("#f6e3d4", "#a86950"),
    "Mono":       ("#e8e8e8", "#7d7d7d"),
    "Night":      ("#999999", "#334455"),
}

DEFAULT_LIGHT, DEFAULT_DARK = THEMES["Classic"]


def theme_colors(name: str, fallback_light: str, fallback_dark: str):
    return THEMES.get(name, (fallback_light, fallback_dark))
