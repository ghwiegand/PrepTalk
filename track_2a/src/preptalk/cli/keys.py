"""Read terminal navigation keys, restoring normal line input when the menu closes."""

import os
import select
import sys


class KeyReader:
    def __enter__(self):
        self.saved = None
        if os.name != "nt":
            import termios
            import tty

            self.fd = sys.stdin.fileno()
            if os.isatty(self.fd):
                self.saved = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
        return self

    def __exit__(self, *_):
        if self.saved is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def read(self, timeout=None):
        try:
            if os.name == "nt":
                import msvcrt

                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    return {"H": "up", "P": "down", "K": "back", "M": "right", "G": "home", "O": "end",
                            "I": "page_up", "Q": "page_down"}.get(msvcrt.getwch(), "")
            else:
                if timeout is not None and not select.select([self.fd], [], [], timeout)[0]:
                    return ""
                char = os.read(self.fd, 1).decode("ascii", errors="ignore")
            if not char or char in ("\x03", "\x04", "q", "Q"):
                return "quit"
            if char == "\x1b":
                if os.name == "nt":
                    return "back"
                sequence = b""
                while select.select([self.fd], [], [], 0.08)[0]:
                    part = os.read(self.fd, 1)
                    if not part:
                        break
                    sequence += part
                    if len(sequence) >= 2 and (part.isalpha() or part == b"~"):
                        break
                    if len(sequence) >= 16:
                        break
                if not sequence:
                    return "back"
                if sequence.startswith((b"[", b"O")):
                    if sequence.endswith(b"~"):
                        return {b"[1~": "home", b"[4~": "end", b"[5~": "page_up", b"[6~": "page_down",
                                b"[7~": "home", b"[8~": "end"}.get(sequence, "")
                    return {b"A": "up", b"B": "down", b"C": "right", b"D": "back", b"H": "home",
                            b"F": "end"}.get(sequence[-1:], "")
                return ""
            return {" ": "space", "\r": "enter", "\n": "enter", "\t": "down"}.get(char, "")
        except (KeyboardInterrupt, EOFError):
            return "quit"
