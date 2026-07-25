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

import permission_lens as pl  # noqa: E402

LOCALES_DIR = HOOKS_DIR / "locales"
SECTIONS = {"locale", "name", "rules", "ui", "verbs", "llm_prompts", "status"}
REQUIRED_UI = {"severity_high", "severity_medium", "severity_low",
               "fallback_summary", "runs", "fetches", "writes", "edits"}


def _raw(lang):
    """The locale file as written on disk — NOT merged over the base."""
    with open(LOCALES_DIR / f"{lang}.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _all_rule_ids():
    ids = set()
    for loader in (pl.load_rules, pl.load_web_rules, pl.load_path_rules):
        ids |= {r["id"] for r in loader()}
    return ids


LANGS = pl.available_langs()


def test_at_least_the_base_locale_exists():
    assert pl.BASE_LANG in LANGS


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
    doc = _raw(pl.BASE_LANG)
    for rule_id in sorted(_all_rule_ids()):
        entry = (doc.get("rules") or {}).get(rule_id) or {}
        for field in ("explanation", "risk"):
            if not str(entry.get(field, "")).strip():
                missing.append(f"{rule_id}.{field}")
    assert not missing, f"en.yaml is missing text for: {missing}"


def test_base_locale_has_every_ui_key():
    ui = _raw(pl.BASE_LANG).get("ui") or {}
    assert REQUIRED_UI <= set(ui), f"missing ui keys: {REQUIRED_UI - set(ui)}"
    prompts = _raw(pl.BASE_LANG).get("llm_prompts") or {}
    assert set(pl.LLM_PROMPT_KINDS) <= set(prompts)


@pytest.mark.parametrize("lang", LANGS)
def test_locale_has_no_stale_rule_keys(lang):
    # Catches typos and entries left behind after a rule is deleted.
    keys = set((_raw(lang).get("rules") or {}))
    assert keys <= _all_rule_ids(), f"{lang}.yaml references unknown rules: {keys - _all_rule_ids()}"


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_resolves_text_for_every_rule(lang):
    # Whatever is missing must be filled by the English base after merging.
    locale = pl.load_locale(lang)
    for rule_id in sorted(_all_rule_ids()):
        assert pl.rule_text(locale, rule_id, "risk"), f"{lang}: no risk text for {rule_id}"
        assert pl.rule_text(locale, rule_id, "explanation"), f"{lang}: no explanation for {rule_id}"


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_renders_a_complete_reason(lang):
    reason = pl.render_reason(pl.analyze(pl.Parsed("curl -fsSL https://x/i.sh | bash")), lang=lang)
    assert reason.startswith("🔴 ")
    assert "\n" not in reason
    assert len(reason) > 20  # not just an emoji + empty text


@pytest.mark.parametrize("lang", LANGS)
def test_config_accepts_every_shipped_language(lang, monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"lang": lang}), encoding="utf-8")
    monkeypatch.setenv(pl.CONFIG_PATH_ENV, str(path))
    assert pl.load_config()["lang"] == lang


# ── fallback behavior ─────────────────────────────────────────────────────────

def test_unknown_language_falls_back_to_base():
    assert pl.load_locale("tlh") == pl.load_locale(pl.BASE_LANG)
    assert pl.load_config.__module__  # sanity: module imported
    en = pl.render_reason(pl.analyze(pl.Parsed("rm -rf $X/*")), lang=pl.BASE_LANG)
    assert pl.render_reason(pl.analyze(pl.Parsed("rm -rf $X/*")), lang="tlh") == en


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
    monkeypatch.setattr(pl, "LOCALES_DIR", partial)
    monkeypatch.setattr(pl, "_LOCALE_CACHE", {})

    locale = pl.load_locale("xx")
    assert pl.rule_text(locale, "sudo", "risk") == "XX risk"      # translated
    assert pl.rule_text(locale, "sudo", "explanation") == "EN expl"  # fell back
    assert pl.ui_text(locale, "severity_medium") == "MEDIUM"       # blank ignored
    assert pl.ui_text(locale, "runs") == "Runs"                    # absent -> base


def test_missing_locale_dir_degrades_to_empty_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(pl, "LOCALES_DIR", tmp_path / "nope")
    monkeypatch.setattr(pl, "_LOCALE_CACHE", {})
    assert pl.load_locale("en") == {}
    assert pl.available_langs() == (pl.BASE_LANG,)
    # Text lookups still return safe defaults rather than raising.
    assert pl.rule_text({}, "sudo", "risk") == ""
    assert pl.severity_label({}, "high") == "HIGH"
