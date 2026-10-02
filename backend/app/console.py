import sys


def utf8_console() -> None:
    """Windows consoles default to a legacy code page and mangle "·", "…" and "→". Call first in every CLI."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
