"""Read optional user-request context from a Claude Code transcript."""
import json
import os

import traceback
from .util import log_debug, one_line

# Transcript contents are untrusted input to the optional model note.


_TRANSCRIPT_TAIL_BYTES = 4 * 1024 * 1024  # cap the scan on very long sessions
# Claude transcript record used by the current adapter.
_TASK_KEY = ("last-prompt", "lastPrompt")
TASK_CONTEXT_MAX_CHARS = 400


def _scan_transcript(path, wanted):
    """Latest value of each wanted (line type -> field) pair. Best effort."""
    found = {}
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if size > _TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - _TRANSCRIPT_TAIL_BYTES)
                fh.readline()  # discard the partial line
            for line in fh:
                # Cheap pre-filter: these lines are a tiny fraction of a transcript.
                if not any(f'"{kind}"' in line for kind, _ in wanted):
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                for kind, key in wanted:
                    if entry.get("type") == kind and isinstance(entry.get(key), str):
                        found[kind] = entry[key].strip()
    except Exception:
        log_debug("transcript %s unreadable: %s" % (path, traceback.format_exc()))
    return found


def task_context(event, max_chars=TASK_CONTEXT_MAX_CHARS):
    """Read and truncate the latest request, or return an empty string.

    The caller must enforce llm.send_task_context before invoking this reader."""
    path = (event or {}).get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    text = _scan_transcript(path, (_TASK_KEY,)).get(_TASK_KEY[0], "")
    text = one_line(text)
    return text[:max_chars - 1] + "…" if len(text) > max_chars else text
