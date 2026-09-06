#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Display the last recorded check, daily counters and model-note status.

Run with uv run scripts/approval-lens-status.py. Uses this checkout's config and locale."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import lens as al  # noqa: E402

SEVERITY_EMOJI = al.SEVERITY_EMOJI

# English defaults, used if a locale file is missing or PyYAML isn't available.
FALLBACK = {
    "tier2_never": "no call has reached the threshold yet",
    "tier2": "Model note: {state}",
    "tier2_off": "not enabled",
    "tier2_skipped": "skipped (subject too long)",
    "tier2_cached": "served from cache",
    "tier2_no_credential": "API key unavailable",
    "tier2_empty": "no answer (timeout or API error)",
    "tier2_ok": "working",
    "tier2_filtered": "omitted (safety verdict)",
    "tier2_error": "internal error",
    "running_vs_repo": "Approval Lens {running} (last check) · checkout {repo}. Check which plugin copy is loaded.",
    "newer_installed": "{newest} is cached; the last check used {running}. Check the loaded version.",
    "none": "no match",
    "asked": "confirmation requested",
    "silent": "no confirmation requested",
    "last": "last check {age} ({tool} · {what})",
    "today": "today: {total} checked · 🔴 {high} · 🟡 {medium} · 🟢 {low} · no match {none} · confirmation requests {asked}",
    "empty": "no invocations recorded yet. Run any Bash/WebFetch/Write/Edit in a plugin-enabled session first (heartbeat: {path})",
    "stale_day": "(counters are from {day}, not today)",
    "s": "{n}s ago",
    "m": "{n} min ago",
    "h": "{n} h ago",
    "d": "{n} d ago"
}


def _text(locale, key):
    return al.ui_text(locale, key, FALLBACK[key], section="status")


def _version():
    manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "?")
    except Exception:
        return "?"


def _installed_versions():
    """List versions found in the Claude plugin cache, newest last.

    A cached version is not necessarily the one handling current calls."""
    root = Path.home() / ".claude" / "plugins" / "cache"
    found = set()
    try:
        for manifest in root.glob("*/approval-lens/*/.claude-plugin/plugin.json"):
            try:
                v = json.loads(manifest.read_text(encoding="utf-8")).get("version")
            except Exception:
                continue
            if isinstance(v, str) and v:
                found.add(v)
    except Exception:
        return []
    return sorted(found, key=_version_key)


def _version_key(v):
    return [int(part) if part.isdigit() else -1 for part in v.split(".")]


def _age(locale, seconds):
    for key, size in (("s", 90), ("m", 90 * 60), ("h", 36 * 3600)):
        if seconds < size:
            unit = {"s": 1, "m": 60, "h": 3600}[key]
            return _text(locale, key).format(n=int(seconds // unit))
    return _text(locale, "d").format(n=int(seconds // 86400))


def main():
    locale = al.load_locale(al.load_config()["lang"])
    hb_path = al.cache_dir() / al.HEARTBEAT_FILE
    try:
        hb = json.loads(hb_path.read_text(encoding="utf-8"))
        hb = hb if isinstance(hb, dict) else {}
    except Exception:
        hb = {}

    # Compare the checkout with the version recorded by the last hook call.
    repo, running = _version(), str(hb.get("running") or "")
    installed = _installed_versions()
    newest = installed[-1] if installed else ""
    if running and running != repo:
        print(_text(locale, "running_vs_repo").format(running=running, repo=repo))
    else:
        print(f"Approval Lens {repo}")
    # The trap this catches: publish succeeded, so the newest build is on disk
    # and the repo looks current, yet every call is still handled by whatever
    # version the session bound to at startup.
    # Strictly newer, not merely different: running a build that is AHEAD of the
    # cache is the normal state when testing from the checkout, and warning
    # about it told the reader to restart in order to downgrade.
    if newest and running and _version_key(newest) > _version_key(running):
        print(_text(locale, "newer_installed").format(newest=newest, running=running))
    last = hb.get("last")
    if not isinstance(last, dict) or not isinstance(last.get("ts"), (int, float)):
        print(_text(locale, "empty").format(path=hb_path))
        return

    sev = last.get("severity")
    what = f"{SEVERITY_EMOJI[sev]} {al.severity_label(locale, sev)}" \
        if sev in SEVERITY_EMOJI else _text(locale, "none")
    what += " · " + _text(locale, "asked" if last.get("asked") else "silent")
    print(_text(locale, "last").format(
        age=_age(locale, max(0, time.time() - last["ts"])),
        tool=last.get("tool", "?"), what=what))

    counts = hb.get("counts") if isinstance(hb.get("counts"), dict) else {}
    line = _text(locale, "today").format(**{
        k: counts.get(k, 0)
        for k in ("total", "high", "medium", "low", "none", "asked")})
    today = time.strftime("%Y-%m-%d")
    if hb.get("today") and hb["today"] != today:
        line += " " + _text(locale, "stale_day").format(day=hb["today"])
    print(line)

    # Tier 2 is opt-in and degrades silently by design; without this line
    # "disabled", "no credential" and "network error" are indistinguishable.
    if (al.load_config().get("llm") or {}).get("enabled"):
        # From the last call that actually reached Tier 2 — benign calls never
        # do, and they must not overwrite this.
        t2 = hb.get("tier2") if isinstance(hb.get("tier2"), dict) else {}
        outcome = t2.get("outcome")
        key = f"tier2_{outcome}" if outcome in al.TIER2_OUTCOMES else "tier2_never"
        state = _text(locale, key)
        if isinstance(t2.get("ts"), (int, float)):
            state += f" ({_age(locale, max(0, time.time() - t2['ts']))})"
        print(_text(locale, "tier2").format(state=state))


if __name__ == "__main__":
    main()
