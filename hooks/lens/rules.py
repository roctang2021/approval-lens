"""Loading rule data and deciding which rules a command matches."""
import re

from .locales import SEVERITY_ORDER
from .paths import PATH_RULES_PATH, RULES_PATH, WEB_RULES_PATH
from .predicates import PREDICATES, flag_disarms
from .util import log_debug

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_RULES_CACHE = {}  # keyed by yaml path -> compiled rule list


def _load_rules_from(path, default_field="path"):
    if path in _RULES_CACHE:
        return _RULES_CACHE[path]
    if yaml is None:
        # Missing PyYAML disables rule loading; keep a debug diagnostic.
        log_debug("rules: PyYAML unavailable, %s loads as empty" % path)
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
            # Optional guard: fullmatched against actual command names,
            # including wrappers, never arbitrary argv operands.
            "verb": re.compile(raw["verb"]) if raw.get("verb") else None,
            # A real downstream pipeline/process-input receiver, after unwrapping.
            "pipe_to": re.compile(raw["pipe_to"]) if raw.get("pipe_to") else None,
            # Optional inverse guard: verbs that make the match inert. `echo`
            # printing a path is not a read of that path.
            "not_verb": re.compile(raw["not_verb"]) if raw.get("not_verb") else None,
            "predicate": raw.get("predicate"),
            # segment (default) | pipeline | process | argv | redirect
            "scope": raw.get("scope", "segment"),
            # Flags that disable the operation on this stage, such as --dry-run.
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
    """Match shell rules and attach evidence, highest severity first."""
    rules = rules if rules is not None else load_rules()
    matches = []
    for rule in rules:
        subject = _matching_subject(rule, parsed)
        if subject is not None:
            # Never mutate a cached rule. Evidence belongs to this invocation
            # and is passed to the detail extractor with the matching rule.
            matches.append({**rule, "_match_subject": subject})
    return _sort_by_severity(matches)


def _command_names(sc):
    """Executable names for a stage, including supported wrappers."""
    return sc.command_names()


# Evaluate guards per stage: an echo or --dry-run elsewhere in the
# command must not suppress a match on this stage.

def _runs_verb(rule, sc):
    """Match executable names on this stage, excluding ordinary arguments."""
    return any(rule["verb"].fullmatch(name) for name in sc.command_names())


def _is_inert(rule, sc):
    """`not_verb`: printing a path is not touching it — for this stage only."""
    not_verb = rule["not_verb"]
    return bool(not_verb) and any(not_verb.fullmatch(name) for name in sc.command_names())


def _is_disarmed(rule, sc):
    """`without_flags`, read off the stage that invokes the verb."""
    return any(flag_disarms(sc.unwrap(), flag) for flag in rule["without_flags"])


def _actor_stages(rule, parsed):
    """The stages that could be the one this rule is about."""
    stages = [sc for sc in parsed.simple_commands if not _is_inert(rule, sc)]
    if rule["verb"]:
        stages = [sc for sc in stages
                  if _runs_verb(rule, sc) and not _is_disarmed(rule, sc)]
    return stages


def _matching_subject(rule, parsed):
    """The actual matching stage/connection/target, or None for no match."""
    actors = _actor_stages(rule, parsed)
    if not actors and (rule["verb"] or rule["not_verb"]):
        return None
    if rule["predicate"]:
        fn = PREDICATES.get(rule["predicate"])
        sc = fn(parsed) if fn else None
        return sc.raw if sc is not None else None
    regex = rule["regex"]
    scope = rule["scope"]
    sink = rule.get("pipe_to")
    if scope == "pipeline" and sink:
        for pipeline in parsed.pipelines:
            for i, sc in enumerate(pipeline):
                if sc not in actors or (regex and not regex.search(sc.match_text())):
                    continue
                for j in range(i + 1, len(pipeline)):
                    if sink.fullmatch(pipeline[j].unwrap().name):
                        return " | ".join(stage.raw for stage in pipeline[i:j + 1])
        return None
    if scope == "process" and sink:
        for receiver, body in parsed.process_inputs:
            if sink.fullmatch(receiver.unwrap().name):
                for sc in _actor_stages(rule, body):
                    if not regex or regex.search(sc.match_text()):
                        return sc.raw
        return None
    if not regex:
        return None
    for sc in actors:
        if scope in ("argv", "redirect"):
            subjects = sc.path_tokens() if scope == "argv" else sc.redirect_targets()
            for subject in subjects:
                if regex.search(subject):
                    return subject
        elif regex.search(sc.match_text()):
            return sc.raw
    return None


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
