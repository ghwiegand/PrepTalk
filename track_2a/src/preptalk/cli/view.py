"""Shared terminal layout for setup, text chat, and voice conversations."""

from collections import deque
import os
import shutil
import textwrap
import threading
import time
import unicodedata

from .keys import KeyReader
from .orb import FPS, render_orb


class ReturnToMenu(Exception):
    """The user confirmed leaving the current interview for the main menu."""


def cells(text):
    """Count terminal cells, including wide glyphs and combining accents."""
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in text)


def cell_chunks(text, width):
    chunk, used = "", 0
    for char in text:
        size = cells(char)
        if used + size > width and chunk:
            yield chunk
            chunk, used = "", 0
        chunk += char
        used += size
    if chunk:
        yield chunk


def input_rows(value, width):
    """Character ranges for visual input lines, leaving a cell for the end cursor."""
    rows, start, used = [], 0, 0
    for index, char in enumerate(value):
        size = cells(char)
        if used + size > width:
            rows.append((start, index))
            start, used = index, 0
        used += size
    rows.append((start, len(value)))
    if used >= width:
        rows.append((len(value), len(value)))
    return rows


def input_row(rows, position):
    return max(index for index, (start, _) in enumerate(rows) if start <= position)


class TerminalView:
    def __init__(self, ui):
        self.ui = ui
        self.entries = deque(maxlen=2000)
        self.footer = []
        self.audio_level = 0
        self._started = time.monotonic()
        self.reduced_motion = os.environ.get("PREPTALK_REDUCED_MOTION") == "1"
        self.offset = 0
        self.editing = None
        self.confirmation = None
        self.menu = None
        self.progress = None
        self._previous = []
        self._size = None
        self._cursor = False
        self._lock = threading.RLock()

    @property
    def dimensions(self):
        size = shutil.get_terminal_size()
        columns, rows = max(12, size.columns), max(4, size.lines)
        sidebar = columns >= 72 and rows >= 18
        right_width = min(59, max(23, columns // 3))
        return columns, rows, columns - right_width - 2 if sidebar else columns - 1, sidebar

    @property
    def width(self):
        return self.dimensions[2]

    def append(self, text="", style=None):
        with self._lock:
            self.menu = None
            self.entries.append((str(text), style))
            self.offset = 0
            self.render()

    def start_chat(self):
        with self._lock:
            self.menu = None
            self.entries.clear()
            self.footer = []
            self.progress = None
            self.offset = self.audio_level = 0

    def show_menu(self, rows, footer, focus):
        with self._lock:
            self.menu = (rows, focus)
            self.footer = footer
            self.progress = None
            self.audio_level = 0
            self.render()

    def set_progress(self, progress):
        with self._lock:
            self.progress = progress
            self.render()

    def _progress_entries(self, bar_width=18):
        if not self.progress:
            return []
        progress = self.progress
        label = (self.ui.text["question"].format(**progress) if progress["phase"] == "interview"
                 else self.ui.text[progress["phase"]])
        size = max(1, bar_width)
        filled = size * progress["completed"] // progress["total"] if progress["total"] else 0
        entries = [(label, "1;36"), ("[" + "━" * filled + "·" * (size - filled) + "]", "36"),
                   (self.ui.text["setup_completed" if progress["phase"] == "setup" else "pane_completed"].format(
                       **progress), "2")]
        if progress["phase"] == "interview" and progress.get("follow_up"):
            entries.append((self.ui.text["follow_up"], "2"))
        return entries

    def set_footer(self, lines, audio_level=None):
        with self._lock:
            self.footer = lines
            if audio_level is not None:
                self.audio_level = max(0, min(1, audio_level))
            self.render()

    def _wrap(self, entries, width):
        result = []
        for text, style in entries:
            for line in text.split("\n"):
                wrapped = textwrap.wrap(line, width=max(1, width - 4), replace_whitespace=False,
                                        drop_whitespace=not line.startswith(" ")) or [""]
                for part in wrapped:
                    result.extend((("  " + chunk) if chunk else "", style)
                                  for chunk in (list(cell_chunks(part, max(1, width - 4))) or [""]))
        return result

    def _input_width(self, label):
        return max(2, self.width - cells(f"  {label} › ") - 2)

    def _layout(self):
        columns, height, width, sidebar = self.dimensions
        left = [("", None)] * height
        language = self.ui.text["language"]
        title = "  PrepTalk" + " " * max(1, columns - len(language) - 13) + language
        left[1] = (title[:columns - 1], "1;36")
        if height > 4:
            left[2] = ("  " + textwrap.shorten(self.ui.text["tagline"], width=columns - 3, placeholder="…"), "2")
            left[3] = ("  " + "─" * (columns - 3), "2")

        footer = self._wrap(self.footer, width)
        cursor = None
        if self.confirmation is not None:
            footer = self._wrap([(self.ui.text["leave_question"], "1")], width)
            for choice, name in ((True, "yes"), (False, "no")):
                selected = choice == self.confirmation
                footer.append((f"  {'›' if selected else ' '} {self.ui.text[name]}", "1;36" if selected else None))
            footer.extend(self._wrap([(self.ui.text["confirm_help"], "2")], width))
        elif self.editing is not None:
            label, value, position = self.editing
            prefix = f"  {label} › "
            rows = input_rows(value, self._input_width(label))
            row = input_row(rows, position)
            capacity = max(1, min(6, height // 2 - len(footer)))
            first = max(0, min(row - capacity + 1, len(rows) - capacity))
            cursor_index = len(footer) + row - first
            for index, (start, end) in enumerate(rows[first:first + capacity]):
                footer.append(((prefix if index == 0 else " " * cells(prefix)) + value[start:end], None))
            cursor = (height - len(footer) + cursor_index, cells(prefix + value[rows[row][0]:position]) + 1)
        footer = footer[-max(1, height // 2):]
        bottom = height - len(footer) - 2
        top = min(5, max(0, bottom - 1))
        if not sidebar and self.progress and self.menu is None and bottom - top >= 4:
            label = self._progress_entries()[0][0]
            summary = self.ui.text["setup_completed" if self.progress["phase"] == "setup" else "pane_completed"].format(
                **self.progress)
            left[top] = ("  " + textwrap.shorten(f"{label} · {summary}", width=max(1, width - 3),
                                                placeholder="…"), "2")
            left[top + 1] = ("  " + self._progress_entries(min(18, width - 6))[1][0], "36")
            top += 3
        self._page_size = max(1, bottom - top)
        if self.menu is not None:
            rows, focus = self.menu
            transcript = [("  " + next(cell_chunks(text, max(1, width - 4)), ""), style) for text, style in rows]
            start = max(0, min(focus - self._page_size + 1, len(transcript) - self._page_size))
            visible = transcript[start:start + self._page_size]
        else:
            transcript = self._wrap(self.entries, width)
            self._max_offset = max(0, len(transcript) - self._page_size)
            self.offset = min(self.offset, self._max_offset)
            end = len(transcript) - self.offset
            visible = transcript[max(0, end - self._page_size):end]
        for row, line in enumerate(visible, top):
            left[row] = line
        for row, line in enumerate(footer, height - len(footer) - 1):
            left[row] = line

        right_width = columns - width - 2
        progress_lines = self._wrap(self._progress_entries(), right_width + 1) if sidebar else []
        # Reserve space even before the first question so progress never shifts or shrinks the orb.
        progress_reserve = 5 if right_width >= 32 else 7
        orb_space = max(3, height - 6 - progress_reserve - 3)
        orb_height = min(28, orb_space)
        orb_top = 6
        orb_top += (orb_space - orb_height) // 2
        seconds = 0 if self.reduced_motion else int((time.monotonic() - self._started) * FPS) / FPS
        art_rows = (render_orb(right_width, orb_height, seconds,
                               0 if self.reduced_motion else self.audio_level, self.ui.color,
                               accent=self.ui.accent) if sidebar else [])
        progress_top = height - 2 - len(progress_lines)
        frame = []
        for row, (text, style) in enumerate(left):
            if sidebar and 4 <= row < height - 1:
                right = self.ui.style("Coach".center(right_width), "36") if row == 4 else " " * right_width
                if orb_top <= row < orb_top + orb_height:
                    right = art_rows[row - orb_top]
                progress_index = row - progress_top
                if 0 <= progress_index < len(progress_lines):
                    right, right_style = progress_lines[progress_index]
                    right = self.ui.style(right.strip().center(right_width), right_style)
                padded = text + " " * max(0, width - cells(text))
                rendered = self.ui.style(padded, style) if style else padded
                frame.append(rendered + self.ui.style("│", "2") + right)
            else:
                frame.append(self.ui.style(text, style) if style else text)
        return frame, cursor, (columns, height)

    def render(self):
        """Paint changed rows at absolute positions; never scroll the terminal itself."""
        with self._lock:
            frame, cursor, size = self._layout()
            output = ""
            if size != self._size:
                output = "\033[2J"
                self._previous = []
                self._size = size
            for row, line in enumerate(frame):
                if row >= len(self._previous) or line != self._previous[row]:
                    output += f"\033[{row + 1};1H" + line + "\033[K"
            self._previous = frame
            if cursor and (output or cursor != self._cursor):
                output += f"\033[{cursor[0]};{cursor[1]}H\033[?25h"
            elif not cursor and cursor != self._cursor:
                output += "\033[?25l"
            self._cursor = cursor
            if output:
                print(output, end="", flush=True)

    def navigate(self, key):
        if key not in ("up", "down", "page_up", "page_down", "home", "end"):
            return False
        with self._lock:
            self._layout()
            if key == "home":
                self.offset = self._max_offset
            elif key == "end":
                self.offset = 0
            else:
                step = self._page_size if key.startswith("page_") else 1
                self.offset = max(0, min(self._max_offset,
                                        self.offset + (step if key in ("up", "page_up") else -step)))
            self.render()
        return True

    def prompt(self, label, *, confirm_menu=False):
        """Edit inside the left pane, including long or pasted Unicode answers."""
        value, position = "", 0
        goal_column = None
        try:
            with KeyReader() as keyboard:
                while True:
                    self.editing = (label, value, position)
                    self.render()
                    key = keyboard.read(timeout=1 / FPS, text=True)
                    if key == "quit":
                        return None
                    if self.confirmation is not None:
                        if key == "back":
                            self.confirmation = None
                        elif key in ("up", "left", "down", "right", "tab"):
                            self.confirmation = not self.confirmation
                        elif key in ("enter", " "):
                            if self.confirmation:
                                raise ReturnToMenu()
                            self.confirmation = None
                        continue
                    if key == "back":
                        if not confirm_menu:
                            return None
                        self.confirmation = False
                        continue
                    if key == "enter":
                        return value
                    if key in ("page_up", "page_down"):
                        self.navigate(key)
                    elif key in ("up", "down"):
                        rows = input_rows(value, self._input_width(label))
                        row = input_row(rows, position)
                        if goal_column is None:
                            goal_column = cells(value[rows[row][0]:position])
                        target = max(0, min(len(rows) - 1, row + (1 if key == "down" else -1)))
                        start, end = rows[target]
                        position = start
                        while position < end and cells(value[start:position + 1]) <= goal_column:
                            position += 1
                        if target < len(rows) - 1 and position == end:
                            position = max(start, end - 1)
                    elif key == "backspace" and position:
                        value = value[:position - 1] + value[position:]
                        position -= 1
                    elif key == "delete":
                        value = value[:position] + value[position + 1:]
                    elif key in ("left", "right"):
                        position = max(0, min(len(value), position + (1 if key == "right" else -1)))
                    elif key in ("home", "end"):
                        position = 0 if key == "home" else len(value)
                    elif key == "word_left":
                        while position and value[position - 1].isspace():
                            position -= 1
                        while position and not value[position - 1].isspace():
                            position -= 1
                    elif key == "word_right":
                        while position < len(value) and not value[position].isspace():
                            position += 1
                        while position < len(value) and value[position].isspace():
                            position += 1
                    elif len(key) == 1 and key.isprintable():
                        value = value[:position] + key + value[position:]
                        position += 1
                    if key and key not in ("up", "down"):
                        goal_column = None
        finally:
            self.editing = None
            self.confirmation = None
            self.set_footer([])
