"""Turning matched rules into the one line the dialog shows."""
from .config import LANG, MAX_MESSAGE_CHARS
from .locales import (INFO_EMOJI, SEVERITY_EMOJI, SEVERITY_ORDER, load_locale,
                      rule_text, severity_label, ui_text)
from .util import one_line

# ── reason formatting ─────────────────────────────────────────────────────────
#
# The reason renders on the permission dialog as ONE flowing line (the dialog
# collapses \n — probe-verified 2026-07-19), so hierarchy has to come from
# ordering and separators rather than layout:
#
#   {🔴 severity} · {concrete target} · {why this class is risky} · AI: {facts}
#
# Severity leads because it decides whether to keep reading; the target comes
# next because "which host / which file" is the most decision-relevant fact and
# deserves the position the eye lands on first. Model text always comes last,
# behind an explicit "AI:" label — the reader must be able to tell audited rule
# copy from generated text, since only the former is deterministic. An
# unexplained 🤖/📍 emoji did not carry that meaning (owner feedback 2026-07-25).

PART_SEP = " · "
# The model segment is wrapped in parentheses rather than joined with `·`.
# `·` reads as "another item of the same kind", which is wrong for a fallible
# aside sitting beside audited copy; a dash collides with the em dashes the rule
# copy already uses. Parentheses are the standard typographic signal for
# supplementary, subordinate text — they demote it without hiding it (owner
# feedback 2026-07-25: a bare "AI:" read as a debug tag).
AI_WRAP_FALLBACK = " (AI note: {})"


def render_reason(matches, lang=LANG, max_chars=MAX_MESSAGE_CHARS, llm_text=None,
                  detail=""):
    """Matched rules -> the single-line permissionDecisionReason.

    Requires at least one match (the ask gate guarantees it). The risk sentence
    is the top rule's `risk` copy — a self-contained plain-language sentence:
    what this class of call does AND why it matters, no jargon. `detail` is the
    concrete target pulled from the command itself (see extract_detail).
    """
    locale = load_locale(lang)
    top = matches[0]
    sev = top["severity"]
    emoji = SEVERITY_EMOJI.get(sev, INFO_EMOJI)
    parts = [f"{emoji} {severity_label(locale, sev)}"]
    if detail:
        parts.append(detail)
    parts.append(rule_text(locale, top["id"], "risk"))
    # Up to two additional distinct risks (dedupe by category to avoid near-dupes);
    # extras use the short `explanation` phrase and keep their own severity dot,
    # which is what distinguishes them from the headline at a glance.
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
    # Tier 2 goes last so truncation always prefers the deterministic Tier 1
    # content over the model-written extra.
    line = PART_SEP.join(one_line(p) for p in parts)
    if llm_text:
        # The template owns the label, the brackets, and the leading space, so
        # each locale follows its own convention (en " (AI note: {})",
        # zh "（AI 解读：{}）"). A template missing its {} would silently drop the
        # model text, so fall back rather than trust it.
        wrap = ui_text(locale, "ai_wrap", AI_WRAP_FALLBACK)
        if "{}" not in wrap:
            wrap = AI_WRAP_FALLBACK
        line += wrap.format(one_line(llm_text))
    return _truncate(line, max_chars)


def passes_threshold(matches, min_severity):
    """The ask.min_severity gate: a rule match at/above `min_severity` passes.

    'info' passes everything including no-match calls; ask never accepts it, so
    the gate can only fire on an actual match. The branch is kept because
    SEVERITY_ORDER has no entry for 'info' and unknown values must not pass."""
    threshold = SEVERITY_ORDER.get(min_severity, 0)  # "info" and unknown -> 0
    if not matches:
        return threshold <= 0
    return SEVERITY_ORDER.get(matches[0]["severity"], 0) >= threshold


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"
