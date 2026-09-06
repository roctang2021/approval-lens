"""Extract the matching action's target for the explanation, without network access."""
import re

import traceback
from .parsing import Parsed
from .predicates import _rm_commands, _rm_targets
from .util import log_debug, one_line

# Rules opt into a named extractor with detail: <name>. Missing targets
# produce an empty string; extraction does not resolve remote resources.

_URL_IN_TEXT_RE = re.compile(r"[a-zA-Z][\w+.-]*://(?:[^/@?#\s]*@)?([^/:?#\s]+)")
# For dd, identify the of= destination rather than the if= source.
_DD_TARGET_RE = re.compile(r"\bof=(\S+)")
# Device paths can contain hyphens and dots, such as /dev/mapper/vg-root.
_DEVICE_RE = re.compile(r"(/dev/[\w./-]+)")
_DETAIL_MAX = 48


def _detail_url_host(parsed, subject):
    """Host of the first URL in the matching subject."""
    m = _URL_IN_TEXT_RE.search(subject or "")
    return m.group(1) if m else ""


def _detail_rm_target(parsed, subject):
    """Parsed rm targets, without expanding variables or globs."""
    for sc in _rm_commands(parsed or Parsed(subject or "")):
        targets = _rm_targets(sc)
        if targets:
            return " ".join(targets[:2])
    return ""


def _detail_device(parsed, subject):
    """The device being written to/formatted — never the read source."""
    m = _DD_TARGET_RE.search(subject or "") or _DEVICE_RE.search(subject or "")
    return m.group(1) if m else ""


def _detail_path(parsed, subject):
    """The file being written/edited (kept as given, ~ not expanded)."""
    return (subject or "").strip()


DETAIL_EXTRACTORS = {
    "url_host": _detail_url_host,
    "rm_target": _detail_rm_target,
    "device": _detail_device,
    "path": _detail_path,
}


def extract_detail(rule, parsed, subject):
    """Short concrete fact for a matched rule, or "" when there's nothing to add."""
    fn = DETAIL_EXTRACTORS.get(rule.get("detail") or "")
    if not fn:
        return ""
    if "_match_subject" in rule:
        # The analyzer chose this subject when the rule fired. Starting again
        # from the whole command can name a harmless earlier stage's target.
        subject, parsed = rule["_match_subject"], None
    try:
        value = one_line(str(fn(parsed, subject) or ""))
    except Exception:
        # A broken extractor must cost the target name, never the dialog.
        log_debug("detail %s failed: %s" % (rule.get("detail"), traceback.format_exc()))
        return ""
    if len(value) > _DETAIL_MAX:
        value = value[:_DETAIL_MAX - 1] + "…"
    return value
