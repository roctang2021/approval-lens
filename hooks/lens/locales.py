"""Localized rule and UI text with per-key English fallback."""
import traceback
from .util import log_debug
from .paths import LOCALES_DIR

try:
    import yaml
except Exception:  # pragma: no cover - exercised only when pyyaml is missing
    yaml = None

BASE_LANG = "en"
_LOCALE_CACHE = {}

# Merge translations over English so missing or blank strings fall back.


def available_langs():
    """Language codes with a locale file, e.g. ('en', 'ja', 'zh').

    The base language is always included: even with the locales directory
    missing, `lang: "en"` must stay a valid config value (it renders the
    built-in defaults).
    """
    try:
        langs = {p.stem for p in LOCALES_DIR.glob("*.yaml")}
    except Exception:
        log_debug("locales dir %s unreadable: %s" % (LOCALES_DIR, traceback.format_exc()))
        langs = set()
    langs.add(BASE_LANG)
    return tuple(sorted(langs))


def _read_locale(lang):
    if yaml is None:
        log_debug("locales: PyYAML unavailable, %s renders built-in defaults" % lang)
        return {}
    try:
        with open(LOCALES_DIR / f"{lang}.yaml", "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}  # a language with no file at all is normal, not an error
    except Exception:
        log_debug("locale %s unreadable: %s" % (lang, traceback.format_exc()))
        return {}  # broken locale -> base language only


def _merge_locale(base, over):
    merged = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_locale(merged[key], value)
        elif isinstance(value, str):
            if value.strip():  # blank translation -> keep the base string
                merged[key] = value
        elif value is not None:
            merged[key] = value
    return merged


def load_locale(lang):
    """The requested locale merged over the English base, cached per process."""
    if not isinstance(lang, str) or not lang:
        lang = BASE_LANG
    if lang not in _LOCALE_CACHE:
        base = _read_locale(BASE_LANG)
        _LOCALE_CACHE[lang] = base if lang == BASE_LANG else _merge_locale(
            base, _read_locale(lang))
    return _LOCALE_CACHE[lang]


def rule_text(locale, rule_id, field):
    """`explanation` or `risk` for a rule id ("" when absent in every locale)."""
    entry = (locale.get("rules") or {}).get(rule_id) or {}
    value = entry.get(field)
    return value.strip() if isinstance(value, str) else ""


def ui_text(locale, key, default="", section="ui"):
    value = (locale.get(section) or {}).get(key)
    return value if isinstance(value, str) and value.strip() else default


SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
INFO_EMOJI = "ℹ️"


def severity_label(locale, severity):
    return ui_text(locale, f"severity_{severity}", severity.upper())
