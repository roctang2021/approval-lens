"""Whitespace, cache path and opt-in debug logging helpers."""
import os
import unicodedata
from pathlib import Path

CACHE_DIR_ENV = "APPROVAL_LENS_CACHE_DIR"   # test/debug override for the cache dir
DEFAULT_CACHE_DIR = "~/.cache/approval-lens"
DEBUG_ENV = "APPROVAL_LENS_DEBUG"
_BIDI_CONTROLS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def one_line(text):
    """Collapse whitespace and make terminal/bidi controls visible as escapes."""
    return "".join(
        f"\\u{ord(char):04x}"
        if unicodedata.category(char) == "Cc" or char in _BIDI_CONTROLS else char
        for char in " ".join(text.split())
    )


def cache_dir():
    return Path(os.path.expanduser(os.environ.get(CACHE_DIR_ENV) or DEFAULT_CACHE_DIR))


def log_debug(text):
    """Append to the debug log when APPROVAL_LENS_DEBUG is set; else nothing."""
    if not os.environ.get(DEBUG_ENV):
        return
    try:
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "debug.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass
