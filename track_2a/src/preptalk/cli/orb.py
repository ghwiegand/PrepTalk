"""A small terminal orb inspired by adriancodes/ascii-orb's void design.

Original Python renderer: layered spherical texture, a bright inner ring, and audio-driven ripples.
"""

from functools import lru_cache
import math

from .theme import resolve_style

# White body and filaments, with the interface's highlight reserved for small accents.
PALETTE = ("2;37", "37", "1;37", "1;36")
RAMP = " .,:;~-+=*"
FPS = 30


@lru_cache(maxsize=16)
def grid(width, height):
    radius = min((width - 2) / 2, (height - 1) * 0.95)
    return tuple(tuple(((col - (width - 1) / 2) / radius,
                        (row - (height - 1) / 2) * 2 / radius)
                       for col in range(width)) for row in range(height))


def render_orb(width, height, seconds, audio_level=0, color=False, *, accent=None):
    """Render one frame. Idle rotation is slow; speech displacement follows measured PCM levels."""
    level = max(0, min(1, audio_level))
    phase = seconds * 0.12  # A full idle orbit takes about 52 seconds.
    palette = tuple(resolve_style(code, accent) for code in PALETTE) if color else ()
    lines = []
    for row in grid(width, height):
        parts, previous_color = [], None
        for x, y in row:
            radius = math.hypot(x, y)
            char, shade = " ", None
            if radius <= 1.12:
                angle = math.atan2(y, x)
                drift = 0.025 * math.sin(angle * 2 + phase) + 0.012 * math.sin(angle * 5 - phase * 1.3)
                ring_radius = 0.57 + drift + level * 0.08
                ring = math.exp(-((radius - ring_radius) / (0.095 + level * 0.025)) ** 2)
                ring *= 0.8 + 0.2 * math.cos(angle - phase)
                # Independent currents move the shell, inner ring, and fine outer threads in different directions.
                texture = (0.5 + 0.3 * math.sin(x * 11 + y * 17 + phase * 2.3)
                           + 0.2 * math.cos(angle * 5 - phase * 1.7 + radius * 13))
                shell = max(0, 1 - radius) * (0.08 + texture * 0.2)
                core_wave = 0.5 + 0.5 * math.cos(x * 9 - y * 11 - phase * 1.8)
                core = max(0, 1 - radius ** 2) * (0.11 + 0.13 * core_wave)
                thread_radius = 0.79 + 0.04 * math.sin(angle * 3 - phase * 0.7)
                threads = math.exp(-((radius - thread_radius) / 0.035) ** 2)
                threads *= 0.17 * (0.5 + 0.5 * math.cos(angle * 4 + phase * 2))
                ripple = level * 0.15 * math.sin(radius * 22 - seconds * 7) * max(0, 1 - radius)
                density = max(0, min(1, shell + core + ring + threads + ripple))
                if radius > 1:
                    density = 0.03 * (1 - (radius - 1) / 0.12)
                char = RAMP[max(1, round(density * (len(RAMP) - 1)))] if density > 0.025 else " "
                if radius <= 1 and density < 0.2:
                    char = ":" if radius > 0.88 else ";" if threads > 0.08 else "," if texture > 0.6 else "."
                shade = 2 if density > 0.58 else 1 if density > 0.27 else 0
                # Short traveling highlights, rather than coloring an entire side of the ring.
                if ring > 0.35 and math.cos(angle * 3 - phase * 1.4) > 0.97 - level * 0.035:
                    shade = 3
            if color:
                if char != " " and shade != previous_color:
                    parts.append(f"\033[0;{palette[shade]}m")
                    previous_color = shade
            parts.append(char)
        if color and previous_color is not None:
            parts.append("\033[0m")
        lines.append("".join(parts))
    return lines
