"""Turning matched rules into the one line the dialog shows."""
from .config import LANG, MAX_MESSAGE_CHARS
from .locales import (INFO_EMOJI, SEVERITY_EMOJI, SEVERITY_ORDER, load_locale,
                      rule_text, severity_label, ui_text)
from .util import one_line

# Single-line layout: severity, target, rule risk, then an optional model note.

PART_SEP = " · "
# Label the explanation by its purpose; document the provider in configuration.
EXPLANATION_WRAP_FALLBACK = " · What this does: {}"


def render_reason(matches, lang=LANG, max_chars=MAX_MESSAGE_CHARS, llm_text=None,
                  detail=""):
    """Render nonempty, severity-sorted matches as a single-line reason."""
    locale = load_locale(lang)
    top = matches[0]
    sev = top["severity"]
    emoji = SEVERITY_EMOJI.get(sev, INFO_EMOJI)
    parts = [f"{emoji} {severity_label(locale, sev)}"]
    if detail:
        parts.append(detail)
    parts.append(rule_text(locale, top["id"], "risk"))
    # Include up to two other risk categories, using short labels.
    seen = {top["category"]}
    extras = 0
    for rule in matches[1:]:
        if rule["category"] in seen:
            continue
        seen.add(rule["category"])
        e = SEVERITY_EMOJI.get(rule["severity"], INFO_EMOJI)
        parts.append(f"{e} {rule_text(locale, rule['id'], 'explanation')}")
        extras += 1
        if extras == 2:
            break
    # Append the model note last so truncation preserves rule text first.
    line = PART_SEP.join(one_line(p) for p in parts)
    if llm_text:
        # Each locale owns the label and spacing. A missing placeholder would
        # silently drop the model text, so use the fallback template.
        wrap = ui_text(locale, "ai_wrap", EXPLANATION_WRAP_FALLBACK)
        if "{}" not in wrap:
            wrap = EXPLANATION_WRAP_FALLBACK
        line += wrap.format(one_line(llm_text))
    return _truncate(line, max_chars)


def passes_threshold(matches, min_severity):
    """Compare the top match to the threshold. Use a validated ask.min_severity.

    The legacy zero threshold also passes unmatched calls; config excludes it."""
    threshold = SEVERITY_ORDER.get(min_severity, 0)  # "info" and unknown -> 0
    if not matches:
        return threshold <= 0
    return SEVERITY_ORDER.get(matches[0]["severity"], 0) >= threshold


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"
