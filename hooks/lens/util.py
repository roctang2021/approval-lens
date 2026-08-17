"""Small helpers used across layers.

`_log_debug` gates on PERMISSION_LENS_DEBUG internally so that adding a trace to
a swallowed exception costs one line — silently discarded failures cost this
project hours more than once."""
import os
from pathlib import Path

CACHE_DIR_ENV = "PERMISSION_LENS_CACHE_DIR"   # test/debug override for the cache dir
DEFAULT_CACHE_DIR = "~/.cache/permission-lens"
DEBUG_ENV = "PERMISSION_LENS_DEBUG"


def one_line(text):
    """Collapse whitespace/newlines so the dialog gets a single tidy line."""
    return " ".join(text.split())


def cache_dir():
    return Path(os.path.expanduser(os.environ.get(CACHE_DIR_ENV) or DEFAULT_CACHE_DIR))


def log_debug(text):
    """Append to the debug log when PERMISSION_LENS_DEBUG is set; else nothing."""
    if not os.environ.get(DEBUG_ENV):
        return
    try:
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "debug.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass
