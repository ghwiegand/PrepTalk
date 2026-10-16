"""Read terminal navigation keys, restoring normal line input when the menu closes."""

import os
import codecs
import select
import sys


class KeyReader:
    def __enter__(self):
        self.saved = None
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        if os.name != "nt":
            import termios
            import tty

            self.fd = sys.stdin.fileno()
            if os.isatty(self.fd):
                self.saved = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd, when=termios.TCSANOW)
        return self

    def __exit__(self, *_):
        if self.saved is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def read(self, timeout=None, *, text=False):
        try:
            if os.name == "nt":
                import msvcrt

                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    return {"H": "up", "P": "down", "K": "left" if text else "back", "M": "right",
                            "G": "home", "O": "end", "I": "page_up", "Q": "page_down",
                            "S": "delete"}.get(msvcrt.getwch(), "")
            else:
                if timeout is not None and not select.select([self.fd], [], [], timeout)[0]:
                    return ""
                data = os.read(self.fd, 1)
                if not data:
                    return "quit"
                char = self.decoder.decode(data)
                if not char:  # A UTF-8 character may span multiple reads.
                    return ""
            if not char or char in ("\x03", "\x04") or (not text and char in ("q", "Q")):
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
                                b"[7~": "home", b"[8~": "end", b"[3~": "delete"}.get(sequence, "")
                    return {b"A": "up", b"B": "down", b"C": "right", b"D": "left" if text else "back", b"H": "home",
                            b"F": "end"}.get(sequence[-1:], "")
                return ""
            if text:
                return {"\r": "enter", "\n": "enter", "\x7f": "backspace", "\b": "backspace"}.get(
                    char, char if char.isprintable() else "")
            return {" ": "space", "\r": "enter", "\n": "enter", "\t": "down"}.get(char, "")
        except (KeyboardInterrupt, EOFError):
            return "quit"
