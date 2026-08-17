"""The developer's current request, read from the session transcript.

The one place the plugin reads what the human typed, and it leaves the machine
only when llm.send_task_context is explicitly on."""
import json
import os

from .util import one_line

# ── task context (opt-in) ─────────────────────────────────────────────────────
#
# The one place the plugin reads what the human actually typed. Read from the
# session transcript, one line, capped — and it leaves the machine only when
# llm.send_task_context is explicitly on. It can enrich the Tier 2 sentence but
# never influences severity or whether the dialog appears, because it is
# attacker-reachable text like any other input.


_TRANSCRIPT_TAIL_BYTES = 4 * 1024 * 1024  # cap the scan on very long sessions
# The transcript also records the developer's current request as its own line
# (verified 2026-07-19). Used ONLY when llm.send_task_context is on.
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
        pass
    return found


def task_context(event, max_chars=TASK_CONTEXT_MAX_CHARS):
    """The developer's current request, or "" — gated by llm.send_task_context.

    This is the only place the plugin reads what the human actually typed, and
    it leaves the machine only when that setting is explicitly on.
    """
    path = (event or {}).get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    text = _scan_transcript(path, (_TASK_KEY,)).get(_TASK_KEY[0], "")
    text = one_line(text)
    return text[:max_chars - 1] + "…" if len(text) > max_chars else text
