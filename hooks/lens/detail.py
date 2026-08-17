"""The concrete fact a rule names on the dialog.

Rule copy describes a CATEGORY of risk; these pull the specific target out of
the command itself — offline, no model, no network, no privacy cost."""
import re

from .parsing import Parsed
from .predicates import _rm_commands, _rm_targets
from .util import one_line

# ── detail extraction ─────────────────────────────────────────────────────────
#
# Rule copy describes a CATEGORY of risk ("downloads a script and runs it").
# The dialog is far more useful when it also names the concrete thing at hand
# ("from get.docker.com" vs "from a1b2c3.xyz"). Extractors pull that fact out
# of the command itself: offline, no model, no network, no privacy cost. A rule
# opts in via `detail: <name>` in rules*.yaml; anything that can't be resolved
# just yields nothing and the reason renders exactly as before.

_URL_IN_TEXT_RE = re.compile(r"[a-zA-Z][\w+.-]*://(?:[^/@?#\s]*@)?([^/:?#\s]+)")
# `of=` is the DESTINATION — the thing that gets overwritten. Naming the `if=`
# source instead would point at the harmless half of `dd if=/dev/zero of=/dev/disk2`.
_DD_TARGET_RE = re.compile(r"\bof=(\S+)")
# Hyphens and dots are ordinary in device paths — /dev/mapper/vg-root,
# /dev/disk/by-id/ata-Samsung_SSD, /dev/nvme0n1p2. Leaving them out of the
# class silently truncated the target shown on the dialog, which is worse than
# showing none: the reader would check the wrong device.
_DEVICE_RE = re.compile(r"(/dev/[\w./-]+)")
_DETAIL_MAX = 48


def _detail_url_host(parsed, subject):
    """Host of the first URL in the command — who the code/data comes from."""
    m = _URL_IN_TEXT_RE.search(subject or "")
    return m.group(1) if m else ""


def _detail_rm_target(parsed, subject):
    """What an rm -r would actually delete."""
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
    try:
        value = one_line(str(fn(parsed, subject) or ""))
    except Exception:
        return ""
    if len(value) > _DETAIL_MAX:
        value = value[:_DETAIL_MAX - 1] + "…"
    return value
