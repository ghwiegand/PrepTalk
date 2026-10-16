"""Shared highlight color, with standard ANSI fallbacks for older terminals."""

import os

ACCENT_HEX = "#8FC7D1"
ACCENT_RGB = "38;2;143;199;209"


def accent_code():
    term = os.environ.get("TERM", "").lower()
    program = os.environ.get("TERM_PROGRAM", "").lower()
    if (os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
            or program in ("ghostty", "iterm.app", "wezterm", "vscode", "alacritty")
            or os.environ.get("GHOSTTY_RESOURCES_DIR") or os.environ.get("KITTY_WINDOW_ID")
            or "direct" in term or term in ("xterm-ghostty", "xterm-kitty")):
        return ACCENT_RGB
    return "38;5;116" if "256color" in term else "36"


def resolve_style(code, accent=None):
    """Treat the existing cyan style token as the application's highlight role."""
    accent = accent or accent_code()
    return ";".join(accent if token == "36" else token for token in code.split(";"))
