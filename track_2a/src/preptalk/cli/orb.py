"""A small terminal orb inspired by adriancodes/ascii-orb's void design.

Original Python renderer: dim spherical texture, a bright inner ring, and audio-driven ripples.
"""

from functools import lru_cache
import math

PALETTE = ((110, 118, 129), (139, 148, 158), (240, 246, 252), (47, 129, 247))
RAMP = " .:-=+*#"
FPS = 30


@lru_cache(maxsize=16)
def grid(width, height):
    radius = min((width - 2) / 2, (height - 1) * 0.95)
    return tuple(tuple(((col - (width - 1) / 2) / radius,
                        (row - (height - 1) / 2) * 2 / radius)
                       for col in range(width)) for row in range(height))


def render_orb(width, height, seconds, audio_level=0, color=False):
    """Render one frame. Idle rotation is slow; speech displacement follows measured PCM levels."""
    level = max(0, min(1, audio_level))
    phase = seconds * 0.12  # A full idle orbit takes about 52 seconds.
    lines = []
    for row in grid(width, height):
        parts, previous_color = [], None
        for x, y in row:
            radius = math.hypot(x, y)
            char, shade = " ", None
            if radius <= 1.12:
                angle = math.atan2(y, x)
                drift = 0.035 * math.sin(angle * 2 + phase)
                ring_radius = 0.57 + drift + level * 0.08
                ring = math.exp(-((radius - ring_radius) / (0.095 + level * 0.025)) ** 2)
                ring *= 0.8 + 0.2 * math.cos(angle - phase)
                texture = (0.5 + 0.5 * math.sin(x * 7 + y * 13 + phase))
                shell = max(0, 1 - radius) * (0.06 + texture * 0.2) * min(1, radius * 3)
                ripple = level * 0.15 * math.sin(radius * 22 - seconds * 7) * max(0, 1 - radius)
                density = max(0, min(1, shell + ring + ripple))
                if radius > 1:
                    density = 0.03 * (1 - (radius - 1) / 0.12)
                char = RAMP[max(1, round(density * (len(RAMP) - 1)))] if density > 0.025 else " "
                if radius <= 1 and density < 0.2:
                    char = ":" if radius > 0.88 else "-" if texture > 0.35 else "."
                    if radius < 0.3:
                        char = " "
                shade = 2 if density > 0.58 else 1 if density > 0.27 else 0
                if level > 0.12 and ring > 0.45 and math.cos(angle - phase) > 0.25:
                    shade = 3
            if color:
                if char != " " and shade != previous_color:
                    red, green, blue = PALETTE[shade]
                    parts.append(f"\033[38;2;{red};{green};{blue}m")
                    previous_color = shade
            parts.append(char)
        if color and previous_color is not None:
            parts.append("\033[0m")
        lines.append("".join(parts))
    return lines
