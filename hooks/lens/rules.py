"""Loading rule data and deciding which rules a command matches."""
import os
import re

from .locales import SEVERITY_ORDER
from .paths import PATH_RULES_PATH, RULES_PATH, WEB_RULES_PATH
from .predicates import PREDICATES, has_flag

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

# ── rule engine ───────────────────────────────────────────────────────────────

_RULES_CACHE = {}  # keyed by yaml path -> compiled rule list


def _load_rules_from(path, default_field="path"):
    if path in _RULES_CACHE:
        return _RULES_CACHE[path]
    if yaml is None:
        _RULES_CACHE[path] = []
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rules = []
    for raw in data.get("rules", []):
        rules.append({
            "id": raw["id"],
            "category": raw.get("category", ""),
            "severity": raw.get("severity", "low"),
            "regex": re.compile(raw["regex"]) if raw.get("regex") else None,
            # Optional guard: the program this rule is about. Fullmatched against
            # each argv token's basename, so it is anchored no matter how the
            # YAML writes it. See _verb_matches.
            "verb": re.compile(raw["verb"]) if raw.get("verb") else None,
            # Optional inverse guard: verbs that make the match inert. `echo`
            # printing a path is not a read of that path.
            "not_verb": re.compile(raw["not_verb"]) if raw.get("not_verb") else None,
            "predicate": raw.get("predicate"),
            # whole (default) | segment | argv (per path-like token) |
            # redirect (per > / >> target)
            "scope": raw.get("scope", "whole"),
            # Flags that disarm the rule: `npm publish --dry-run` uploads
            # nothing, so warning about an irreversible publish is a false alarm.
            "without_flags": tuple(raw.get("without_flags") or ()),
            # which subject string a string-rule matches against (see match_string_rules)
            "field": raw.get("field", default_field),
            # optional DETAIL_EXTRACTORS name: the concrete fact to name on the dialog
            "detail": raw.get("detail", ""),
        })  # user-visible text is resolved per language from locales/<lang>.yaml
    _RULES_CACHE[path] = rules
    return rules


def load_rules():
    return _load_rules_from(RULES_PATH)  # Bash rules (name kept for existing tests)


def load_web_rules():
    return _load_rules_from(WEB_RULES_PATH, default_field="url")


def load_path_rules():
    return _load_rules_from(PATH_RULES_PATH)  # default field "path"


def _sort_by_severity(matches):
    matches.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 0), reverse=True)
    return matches


def analyze_command(parsed, rules=None):
    """Bash analyzer: matched rules, highest severity first.

    Named for its input, not generically: the other tools go through
    `match_string_rules`, and a bare `analyze` read as if it handled all four.
    """
    rules = rules if rules is not None else load_rules()
    matches = [rule for rule in rules if _rule_matches(rule, parsed)]
    return _sort_by_severity(matches)


# Programs that run another program: their own name hides the real verb, so a
# stage starting with one is scanned in full. Deliberately excludes anything
# whose argument could look like a command name to a reader (`watch`, `sh -c`).
_VERB_WRAPPERS = {"sudo", "doas", "env", "nohup", "nice", "timeout", "stdbuf",
                  "command", "exec", "xargs"}


def _command_names(sc):
    """Program names in COMMAND position for one pipeline stage.

    Normally just the stage's own verb: in `echo mkfs`, `mkfs` is an argument
    being printed, not a program being run. When the stage starts with a
    wrapper (`sudo curl …`, `env X=1 curl …`, `nice -n 5 curl …`) the wrapper's
    own name tells us nothing, so every token is considered — the wrapper is
    itself proof that a command is being invoked.
    """
    if not sc.name:
        return []
    if sc.name in _VERB_WRAPPERS:
        return [os.path.basename(tok) for tok in sc.argv]
    return [sc.name]


def _verb_matches(rule, parsed):
    """Does the command actually INVOKE the program this rule is about?

    Regexes run against the raw command text, so `echo "curl … | bash"` and
    `git commit -m "fix the curl | bash path"` used to fire 🔴 — the analyzer
    knew better (its quote-aware split sees a single `echo` stage) but the
    rules threw that away. A rule with a `verb:` only fires when some stage
    actually runs that program.

    Quote safety comes for free: a quoted run of words survives shlex as ONE
    token, so an anchored fullmatch can never see the `curl` inside it.
    """
    verb = rule.get("verb")
    if not verb:
        return True
    return any(verb.fullmatch(name)
               for sc in parsed.simple_commands
               for name in _command_names(sc))


def _disarmed_by_flags(rule, parsed):
    """True when a flag on the invoking stage makes this rule inapplicable."""
    without = rule["without_flags"]
    if not without:
        return False
    return any(has_flag(sc, flag)
               for sc in parsed.simple_commands
               for flag in without)


def _rule_matches(rule, parsed):
    if not _verb_matches(rule, parsed):
        return False
    if rule["not_verb"] and any(rule["not_verb"].fullmatch(name)
                                for sc in parsed.simple_commands
                                for name in _command_names(sc)):
        return False
    if rule["predicate"]:
        fn = PREDICATES.get(rule["predicate"])
        return bool(fn and fn(parsed))
    regex = rule["regex"]
    if not regex:
        return False
    if _disarmed_by_flags(rule, parsed):
        return False
    scope = rule["scope"]
    if scope == "segment":
        return any(regex.search(stage) for stage in parsed.stages)
    if scope == "argv":
        return any(regex.search(tok)
                   for sc in parsed.simple_commands for tok in sc.path_tokens())
    if scope == "redirect":
        return any(regex.search(target)
                   for sc in parsed.simple_commands for target in sc.redirect_targets())
    # `code`, not `command`: a heredoc payload that is data must not be scanned
    # as if it were shell (see _strip_heredoc_payloads).
    return bool(regex.search(parsed.code))


def match_string_rules(rules, subjects):
    """Match regex rules against a {field: string} map (WebFetch / Write / Edit).

    `subjects` maps a rule's `field` (e.g. "url", "path", "content") to the
    string that field's rules run against. A rule whose field is absent from
    the map is skipped.
    """
    matches = []
    for rule in rules:
        regex = rule["regex"]
        subject = subjects.get(rule["field"])
        if regex and subject and regex.search(subject):
            matches.append(rule)
    return _sort_by_severity(matches)
