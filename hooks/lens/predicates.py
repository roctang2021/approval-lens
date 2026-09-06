"""Rule conditions that a regex cannot express cleanly.

A rule names one of these in `predicate:`. A predicate returns its matching
SimpleCommand, or None, so the detail extractor gets the same evidence.
`flag_disarms` backs `without_flags:`; both use parsed argv."""
import re


_RECURSIVE_RE = re.compile(r"(^|(?<=[\s-]))(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b", re.IGNORECASE)
_RISKY_TARGET_RE = re.compile(r"(\$\{?\w|[*?\[]|(^|\s)(/|~)($|\s|/))")


def has_flag(sc, flag):
    """Is `flag` present on this stage? Bundling-aware for short options.

    `-f` must be found inside `-fdx`, and `--dry-run` must also match
    `--dry-run=true`, or a rule written against flags is trivially evaded.
    """
    flags, _ = sc.flags_and_args()
    if flag.startswith("--"):
        return any(tok == flag or tok.startswith(flag + "=") for tok in flags)
    letter = flag.lstrip("-")
    return any(not tok.startswith("--") and tok.startswith("-") and letter in tok[1:]
               for tok in flags)


def flag_disarms(sc, flag):
    """Whether a flag enables a no-op mode, including its effective value.

    Presence is insufficient for dry-run: npm accepts false, kubectl accepts
    none, and a later occurrence can override an earlier one. Unknown values
    never suppress a warning.
    """
    if flag not in ("--dry-run", "--dryrun"):
        return has_flag(sc, flag)
    argv = sc.command_argv[1:]
    enabled = False
    i = 0
    while i < len(argv):
        tok = argv[i]
        i += 1
        if tok == "--":
            break
        if tok == "--no-" + flag[2:]:
            enabled = False
            continue
        if tok != flag and not tok.startswith(flag + "="):
            continue
        if "=" in tok:
            value = tok.split("=", 1)[1]
        elif i < len(argv) and (sc.name == "kubectl" or argv[i] in ("true", "false")):
            value = argv[i]
            i += 1
        else:
            value = "true"
        allowed = ("client", "server") if sc.name == "kubectl" else ("true",)
        enabled = value in allowed
    return enabled


def _rm_commands(parsed):
    """Every stage that runs rm, seen through wrappers: `sudo rm`, `xargs rm`.

    `sc.name == "rm"` alone missed `sudo rm -rf /` entirely — the stage's name
    is `sudo` — so the most privileged spelling got only a 🟡 sudo note.
    """
    found = []
    for sc in parsed.simple_commands:
        inner = sc.unwrap()
        if inner.name == "rm":
            found.append(inner)
    return found


def _rm_is_recursive(sc):
    flags, _ = sc.flags_and_args()
    return any(_RECURSIVE_RE.search(f) for f in flags)


def _rm_targets(sc):
    _, args = sc.flags_and_args()
    return args


def _target_is_risky(target):
    # Variable expansion, a glob, or an absolute/home root — the cases where an
    # rm -r can delete far more than the literal path suggests.
    if re.search(r"\$\{?\w", target):
        return True
    if any(g in target for g in "*?[") :
        return True
    stripped = target.strip("'\"")
    if stripped in ("/", "~", "/*", "~/") or stripped.startswith(("/", "~/")):
        return True
    return False


def pred_rm_recursive_risky_target(parsed):
    for sc in _rm_commands(parsed):
        if _rm_is_recursive(sc) and any(_target_is_risky(t) for t in _rm_targets(sc)):
            return sc
    return None


def pred_rm_recursive_plain(parsed):
    for sc in _rm_commands(parsed):
        if not _rm_is_recursive(sc):
            continue
        targets = _rm_targets(sc)
        if targets and not any(_target_is_risky(t) for t in targets):
            return sc
        # `find … | xargs rm -rf` names no target of its own: whatever the pipe
        # delivers is deleted. Unknown is not the same as safe.
        if not targets and "xargs" in sc.wrappers:
            return sc
    return None


PREDICATES = {
    "rm_recursive_risky_target": pred_rm_recursive_risky_target,
    "rm_recursive_plain": pred_rm_recursive_plain,
}
