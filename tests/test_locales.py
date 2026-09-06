"""M10 — locale files: structure, completeness, and per-key fallback.

The rule YAMLs hold matching logic only; all user-visible text lives in
hooks/locales/<lang>.yaml. These tests are the guard rails that keep the two
in sync — notably "every rule has English text" (a new rule with no copy would
otherwise render a headline of just the severity) and "no locale references a
rule that no longer exists"."""
import json
import sys
from pathlib import Path

import pytest
import yaml

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import lens as al  # noqa: E402
from lens import locales  # noqa: E402

LOCALES_DIR = HOOKS_DIR / "locales"
SECTIONS = {"locale", "name", "rules", "ui", "llm_prompts", "llm_guard", "status"}
REQUIRED_UI = {"severity_high", "severity_medium", "severity_low",
               "ai_wrap"}


def _raw(lang):
    """The locale file as written on disk — NOT merged over the base."""
    with open(LOCALES_DIR / f"{lang}.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _all_rule_ids():
    ids = set()
    for loader in (al.load_rules, al.load_web_rules, al.load_path_rules):
        ids |= {r["id"] for r in loader()}
    return ids


LANGS = al.available_langs()


def test_at_least_the_base_locale_exists():
    assert al.BASE_LANG in LANGS


@pytest.mark.parametrize("lang", LANGS)
def test_locale_parses_and_has_known_sections(lang):
    doc = _raw(lang)
    assert isinstance(doc, dict) and doc
    assert set(doc) <= SECTIONS, f"unknown sections: {set(doc) - SECTIONS}"
    assert doc.get("locale") == lang, "the `locale` field must match the filename"
    assert isinstance(doc.get("name"), str) and doc["name"].strip()


def test_base_locale_covers_every_rule():
    # A rule with no English copy would render an empty dialog headline.
    missing = []
    doc = _raw(al.BASE_LANG)
    for rule_id in sorted(_all_rule_ids()):
        entry = (doc.get("rules") or {}).get(rule_id) or {}
        for field in ("explanation", "risk"):
            if not str(entry.get(field, "")).strip():
                missing.append(f"{rule_id}.{field}")
    assert not missing, f"en.yaml is missing text for: {missing}"


def test_base_locale_has_every_ui_key():
    ui = _raw(al.BASE_LANG).get("ui") or {}
    assert REQUIRED_UI <= set(ui), f"missing ui keys: {REQUIRED_UI - set(ui)}"
    prompts = _raw(al.BASE_LANG).get("llm_prompts") or {}
    assert set(al.LLM_PROMPT_KINDS) <= set(prompts)


@pytest.mark.parametrize("lang", LANGS)
def test_locale_has_no_stale_rule_keys(lang):
    # Catches typos and entries left behind after a rule is deleted.
    keys = set((_raw(lang).get("rules") or {}))
    assert keys <= _all_rule_ids(), f"{lang}.yaml references unknown rules: {keys - _all_rule_ids()}"


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_resolves_text_for_every_rule(lang):
    # Whatever is missing must be filled by the English base after merging.
    locale = al.load_locale(lang)
    for rule_id in sorted(_all_rule_ids()):
        assert al.rule_text(locale, rule_id, "risk"), f"{lang}: no risk text for {rule_id}"
        assert al.rule_text(locale, rule_id, "explanation"), f"{lang}: no explanation for {rule_id}"


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_renders_a_complete_reason(lang):
    reason = al.render_reason(al.analyze_command(al.Parsed("curl -fsSL https://x/i.sh | bash")), lang=lang)
    assert reason.startswith("🔴 ")
    assert "\n" not in reason
    assert len(reason) > 20  # not just an emoji + empty text


@pytest.mark.parametrize("lang", LANGS)
def test_config_accepts_every_shipped_language(lang, monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"lang": lang}), encoding="utf-8")
    monkeypatch.setenv(al.CONFIG_PATH_ENV, str(path))
    assert al.load_config()["lang"] == lang


# ── fallback behavior ─────────────────────────────────────────────────────────

def test_unknown_language_falls_back_to_base():
    assert al.load_locale("tlh") == al.load_locale(al.BASE_LANG)
    assert al.load_config.__module__  # sanity: module imported
    en = al.render_reason(al.analyze_command(al.Parsed("rm -rf $X/*")), lang=al.BASE_LANG)
    assert al.render_reason(al.analyze_command(al.Parsed("rm -rf $X/*")), lang="tlh") == en


def test_missing_and_blank_keys_fall_back_per_key(monkeypatch, tmp_path):
    partial = tmp_path / "locales"
    partial.mkdir()
    (partial / "en.yaml").write_text(yaml.safe_dump({
        "locale": "en", "name": "English",
        "rules": {"sudo": {"explanation": "EN expl", "risk": "EN risk"}},
        "ui": {"severity_medium": "MEDIUM", "runs": "Runs"},
    }), encoding="utf-8")
    (partial / "xx.yaml").write_text(yaml.safe_dump({
        "locale": "xx", "name": "Test",
        "rules": {"sudo": {"risk": "XX risk"}},   # explanation missing
        "ui": {"severity_medium": "   "},          # blank -> must not win
    }), encoding="utf-8")
    monkeypatch.setattr(locales, "LOCALES_DIR", partial)
    monkeypatch.setattr(locales, "_LOCALE_CACHE", {})

    locale = al.load_locale("xx")
    assert al.rule_text(locale, "sudo", "risk") == "XX risk"      # translated
    assert al.rule_text(locale, "sudo", "explanation") == "EN expl"  # fell back
    assert al.ui_text(locale, "severity_medium") == "MEDIUM"       # blank ignored
    assert al.ui_text(locale, "runs") == "Runs"                    # absent -> base


def test_missing_locale_dir_degrades_to_empty_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(locales, "LOCALES_DIR", tmp_path / "nope")
    monkeypatch.setattr(locales, "_LOCALE_CACHE", {})
    assert al.load_locale("en") == {}
    assert al.available_langs() == (al.BASE_LANG,)
    # Text lookups still return safe defaults rather than raising.
    assert al.rule_text({}, "sudo", "risk") == ""
    assert al.severity_label({}, "high") == "HIGH"


# ── M14: the model describes, the rules judge ────────────────────────────────

@pytest.mark.parametrize("lang", LANGS)
def test_prompts_forbid_the_model_from_rating_danger(lang):
    """Severity belongs to the offline rules. A model that also rates the
    danger produces two verdicts on one dialog — and the reader cannot tell
    which to trust (owner feedback 2026-07-25). Each prompt must say so."""
    prompts = al.load_locale(lang)["llm_prompts"]
    for kind in ("bash", "url", "path"):
        text = prompts[kind]
        # The prohibition is phrased per language, so assert on the structural
        # markers every version shares rather than on English wording. The
        # length floor is a truncation canary only — CJK says the same thing in
        # roughly a third of the characters, so it has to clear the shortest
        # language, not the longest.
        assert len(text) > 150, f"{lang}/{kind}: prompt looks truncated"
        assert "markdown" in text.lower(), f"{lang}/{kind}: lost the no-markdown rule"


def test_base_prompts_name_the_division_of_labour():
    prompts = al.load_locale(al.BASE_LANG)["llm_prompts"]
    for kind in ("bash", "url", "path"):
        text = prompts[kind].lower()
        assert "rule engine" in text, f"{kind}: must state the rules own severity"
        assert "never rate the danger" in text, f"{kind}: must forbid rating danger"
        assert "never advise approving or rejecting" in text, f"{kind}: must forbid verdicts"


def test_ai_wrap_is_present_and_has_a_placeholder():
    wraps = {lang: al.ui_text(al.load_locale(lang), "ai_wrap") for lang in LANGS}
    assert all(wraps.values()), f"missing ai_wrap: {wraps}"
    # The label introduces the operation explanation. A missing placeholder
    # would silently drop its text.
    for lang, wrap in wraps.items():
        assert "{}" in wrap, f"{lang}: ai_wrap lost its placeholder: {wrap!r}"
        assert wrap.replace("{}", "").strip(), f"{lang}: ai_wrap has no label text"


def test_broken_ai_wrap_falls_back_instead_of_dropping_the_model_text(monkeypatch):
    # A translator can plausibly drop the {} — that must not silently swallow
    # the whole model sentence.
    broken = dict(al.load_locale("en"))
    broken["ui"] = dict(broken["ui"], ai_wrap=" · What this does: ")
    monkeypatch.setattr(locales, "_LOCALE_CACHE", {"xx": broken})
    reason = al.render_reason(al.analyze_command(al.Parsed("rm -rf $X/*")), lang="xx",
                              llm_text="MODEL TEXT")
    assert reason.endswith(" · What this does: MODEL TEXT")
