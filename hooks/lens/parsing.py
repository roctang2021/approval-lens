"""Partial shell parsing for rule matching; this is not a full shell grammar."""
import os
import re
import shlex

from .util import log_debug


# Top-level statement separators and pipeline separators. We split with a
# quote-aware scanner rather than a regex so quoted separators are ignored.
_STATEMENT_SEPS = {";", "\n"}
_TWO_CHAR_OPS = {"&&", "||"}


# Treat heredoc bodies as data unless the receiver runs shell source.
# Unquoted delimiters also evaluate substitutions in the supplying shell.
_HEREDOC_OPEN_RE = re.compile(r'''<<(-?)[ \t]*((?:[\w]|\\.|'[^']*'|"[^"]*")+)''')
# An ssh receiver may execute the heredoc remotely as shell source.
_SHELL_INTERPRETERS = ("bash", "sh", "zsh", "dash", "ksh", "fish", "ssh")

# Supported wrapper programs; other execution forms need their own parsing.
VERB_WRAPPERS = frozenset({"sudo", "doas", "env", "nohup", "nice", "timeout",
                           "stdbuf", "command", "exec", "xargs"})
# Wrapper options that consume the NEXT token as their value, so that
# `sudo -u root rm …` unwraps to `rm` and not to `root`.
_WRAPPER_VALUE_OPTS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T",
             "--user", "--group", "--close-from", "--chdir", "--host", "--prompt",
             "--role", "--type", "--other-user", "--command-timeout", "--chroot", "-R"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e"},
    "xargs": {"-I", "-n", "-P", "-s", "-d", "-a", "-E", "-L", "-i", "-l",
              "--replace", "--max-args", "--max-procs", "--max-chars", "--delimiter",
              "--arg-file", "--eof", "--max-lines"},
}
# Wrappers that take a positional argument before the program (`timeout 10 cmd`).
_WRAPPER_POSITIONALS = {"timeout": 1}
# Shells whose `-c STRING` runs STRING as a command of its own.
_SHELLS_WITH_C = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
_ASSIGNMENT_RE = re.compile(r"^\w+=")
_MAX_NESTING = 4


def _strip_heredoc_payloads(command):
    """Keep shell source and expansions; discard only inert heredoc data."""
    if "<<" not in command:
        return command
    kept, lines = [], command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for stage in _split_pipeline_statements(line):
            for opener in _heredoc_openers(stage):
                delimiter = shlex.split(opener.group(2))[0]
                quoted = any(c in opener.group(2) for c in "'\"\\")
                receiver = SimpleCommand(stage[:opener.start()]).unwrap()
                feeds_shell = receiver.name in _SHELL_INTERPRETERS
                payload = []
                while i < len(lines):
                    candidate = lines[i].lstrip("\t") if opener.group(1) else lines[i]
                    if candidate == delimiter:
                        i += 1
                        break
                    payload.append(lines[i])
                    i += 1
                body = "\n".join(payload)
                if feeds_shell:
                    kept.append(body)
                if not quoted:
                    # Quotes in heredoc DATA do not suppress the supplying
                    # shell's expansions. Only a quoted delimiter does.
                    kept.extend(sub.body for sub in _substitutions(body, heredoc=True))
    return "\n".join(kept)


class Parsed:
    """Best-effort structural view of a shell command string."""

    def __init__(self, command, _depth=0):
        self.command = command
        # `code` is what rules analyze: the command minus any heredoc payload
        # that is data rather than shell. `command` stays verbatim for anything
        # that needs the original text.
        self.code = _strip_heredoc_payloads(command)
        self.has_command_sub = bool(re.search(r"\$\(", command))
        self.has_backtick = "`" in command
        self.has_process_sub = bool(re.search(r"[<>]\(", command))
        # Pipeline stages across every statement, including the bodies of
        # $(...) / `...` / <(...) so `bash <(curl ...)` and `$(curl ... | sh)`
        # are analyzed too — but NOT heredoc payloads that are plain data.
        self.stages = []
        self.simple_commands = []  # list[SimpleCommand]
        self.pipelines = []  # preserve connectivity, not just a flat list of verbs
        self.process_inputs = []  # (receiving stage, parsed <(...) body)
        # Retain source chunks for inspection. Rules use stages and their
        # connections, never a regex over these whole command strings.
        self.code_chunks = [self.code]
        for chunk in _split_statements(self.code):
            pipeline = []
            for stage in _split_pipeline(chunk):
                stage = stage.strip()
                if stage:
                    self.stages.append(stage)
                    sc = SimpleCommand(stage)
                    self.simple_commands.append(sc)
                    pipeline.append(sc)
            if pipeline:
                self.pipelines.append(pipeline)
        # A stage that hands a string to a shell (`bash -c 'curl x | sh'`) runs
        # that string as a command of its own, so its stages are stages here.
        # Bounded, because the nesting is attacker-written text.
        if _depth < _MAX_NESTING:
            for sc in list(self.simple_commands):
                children = [(None, sc.nested_command())]
                children.extend((sub.kind, sub.body) for sub in _substitutions(sc.raw))
                for kind, nested in children:
                    if not nested or not nested.strip():
                        continue
                    inner = Parsed(nested, _depth + 1)
                    self.stages.extend(inner.stages)
                    self.simple_commands.extend(inner.simple_commands)
                    self.code_chunks.extend(inner.code_chunks)
                    self.pipelines.extend(inner.pipelines)
                    self.process_inputs.extend(inner.process_inputs)
                    if kind == "<":
                        self.process_inputs.append((sc, inner))


class SimpleCommand:
    """A single pipeline stage tokenized best-effort into argv."""

    def __init__(self, raw, argv=None, wrappers=()):
        self.raw = raw
        # Wrapper names this view was unwrapped through (see unwrap): () for a
        # stage as written, ("sudo",) for the rm inside `sudo rm -rf /`.
        self.wrappers = tuple(wrappers)
        if argv is None:
            try:
                # posix=True expands quotes but keeps $VAR text literally, which is
                # what we want for target-risk analysis.
                argv = shlex.split(raw, posix=True)
            except ValueError:
                log_debug("parser: unbalanced shell words; using whitespace fallback")
                argv = raw.split()
        self.argv = argv
        # Skip leading `VAR=value` assignments and env/wrappers to find the verb.
        self.name = ""
        for tok in self.argv:
            if "=" in tok and re.match(r"^\w+=", tok):
                continue
            self.name = os.path.basename(tok)
            break

    @property
    def command_argv(self):
        """argv starting at the executable, after leading assignments."""
        i = 0
        while i < len(self.argv) and _ASSIGNMENT_RE.match(self.argv[i]):
            i += 1
        return self.argv[i:]

    def match_text(self):
        """One stage's words, with prose operands kept opaque to regex rules."""
        sc = self.unwrap()
        words = [*sc.wrappers, sc.name, *sc.command_argv[1:]]
        return " ".join("<argument>" if any(c.isspace() for c in word) else word
                        for word in words)

    def unwrap(self):
        """Unwrap supported launchers such as sudo and env.

        Preserve raw source for redirects; return self when no wrapper is found."""
        sc = self
        for _ in range(_MAX_NESTING):
            if sc.name not in VERB_WRAPPERS:
                return sc
            inner = _strip_wrapper(sc.argv, sc.name)
            if not inner:
                return sc
            sc = SimpleCommand(sc.raw, argv=inner, wrappers=sc.wrappers + (sc.name,))
        return sc

    def command_names(self):
        """Executable names including wrappers, excluding ordinary arguments."""
        if not self.name:
            return []
        inner = self.unwrap()
        return list(inner.wrappers) + [inner.name]

    def nested_command(self):
        """Extract shell source from supported -c and eval invocations, or None."""
        sc = self.unwrap()
        argv = sc.command_argv
        if sc.name in _SHELLS_WITH_C:
            # `bash -c STRING [args]`: STRING is the first operand after the
            # options, and -c may be bundled (`bash -lc '…'`, `sh -ec '…'`).
            seen_c = False
            i = 1
            while i < len(argv):
                tok = argv[i]
                i += 1
                if tok == "--":
                    return argv[i] if seen_c and i < len(argv) else None
                if tok in ("--rcfile", "--init-file"):
                    i += 1
                    continue
                if tok.startswith("--"):
                    continue
                if tok.startswith(("-", "+")) and len(tok) > 1:
                    if "c" in tok[1:]:
                        seen_c = tok[0] == "-"
                    if tok[-1] in "oO":  # -o pipefail / -O extglob, also bundled
                        i += 1
                    continue
                return tok if seen_c else None
            return None
        if sc.name == "su":
            for i, tok in enumerate(argv[1:], 1):
                if tok in ("-c", "--command") and i + 1 < len(argv):
                    return argv[i + 1]
                if tok.startswith("--command="):
                    return tok.split("=", 1)[1]
            return None
        if sc.name == "eval":
            return " ".join(argv[1:]) or None
        return None

    def redirect_targets(self):
        """Find output targets after unquoted > or >> operators."""
        targets, i, n, quote = [], 0, len(self.raw), None
        while i < n:
            ch = self.raw[i]
            if quote:
                quote = None if ch == quote else quote
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == ">":
                i += 1
                while i < n and self.raw[i] in ">|&":  # >>, >|, &>
                    i += 1
                while i < n and self.raw[i].isspace():
                    i += 1
                start = i
                while i < n and not self.raw[i].isspace():
                    i += 1
                if i > start:
                    targets.append(self.raw[start:i].strip("'\""))
                continue
            i += 1
        return targets

    def path_tokens(self):
        """Exclude whitespace-containing arguments to reduce prose matches.

        This heuristic also excludes valid paths containing whitespace."""
        return [tok for tok in self.argv if tok and not any(c.isspace() for c in tok)]

    def flags_and_args(self):
        """argv after the command name, split into (flag tokens, positional args)."""
        flags, args = [], []
        options = True
        for tok in self.command_argv[1:]:
            if options and tok == "--":
                options = False
                continue
            (flags if options and tok.startswith("-") else args).append(tok)
        return flags, args


def _strip_wrapper(argv, wrapper):
    """argv of the program a wrapper stage runs, or [] when there is none."""
    argv = list(argv)
    value_opts = _WRAPPER_VALUE_OPTS.get(wrapper, set())
    splits = 0
    positionals = _WRAPPER_POSITIONALS.get(wrapper, 0)
    i = 0
    while i < len(argv) and _ASSIGNMENT_RE.match(argv[i]):
        i += 1  # leading VAR=value assignments
    i += 1      # the wrapper itself
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            i += 1
            break
        if wrapper == "env" and (tok in ("-S", "--split-string")
                                  or tok.startswith(("--split-string=", "-S"))):
            if splits >= _MAX_NESTING:
                return []
            splits += 1
            if tok in ("-S", "--split-string"):
                if i + 1 >= len(argv):
                    return []
                value, consumed = argv[i + 1], 2
            else:
                value = tok.split("=", 1)[1] if tok.startswith("--") else tok[2:]
                consumed = 1
            try:
                argv[i:i + consumed] = shlex.split(value)
            except ValueError:
                log_debug("parser: invalid env split string")
                return []
            continue
        if tok in value_opts:
            i += 2
            continue
        if (tok.startswith("-") and len(tok) > 1) or _ASSIGNMENT_RE.match(tok):
            i += 1  # an option, or `env FOO=1 …`
            continue
        if positionals:
            positionals -= 1
            i += 1
            continue
        break
    return argv[i:]


class _Substitution:
    def __init__(self, kind, body, start, end):
        self.kind, self.body, self.start, self.end = kind, body, start, end


def _substitution_at(text, start):
    """Read a balanced expansion, preserving the quote context at each depth."""
    if text.startswith(("$(", "<(", ">("), start):
        kind, offset, closer = text[start], 2, ")"
    elif text.startswith("`", start):
        kind, offset, closer = "`", 1, "`"
    else:
        return None
    stack = [[closer, None]]
    i = start + offset
    while i < len(text):
        ch = text[i]
        close, quote = stack[-1]
        if quote == "'":
            if ch == "'":
                stack[-1][1] = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == "`" and close == "`":
            stack.pop()
        elif text.startswith("$(", i) or (quote is None and text.startswith(("<(", ">("), i)):
            stack.append([")", None])
            i += 2
            continue
        elif ch == "`":
            stack.append(["`", None])
        elif quote == '"':
            if ch == '"':
                stack[-1][1] = None
        elif ch in ("'", '"'):
            stack[-1][1] = ch
        elif ch == "(":
            stack.append([")", None])
        elif ch == close:
            stack.pop()
        if not stack:
            return _Substitution(kind, text[start + offset:i], start, i + 1)
        i += 1
    return None


def _substitutions(text, heredoc=False):
    """Expansions the shell evaluates here, excluding quoted/escaped literals."""
    i, quote = 0, None
    while i < len(text):
        ch = text[i]
        if not heredoc and quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        sub = _substitution_at(text, i)
        if sub and (sub.kind in ("$", "`") or (quote is None and not heredoc)):
            yield sub
            i = sub.end
            continue
        if not heredoc:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == "#" and (i == 0 or text[i - 1].isspace()):
                end = text.find("\n", i)
                i = len(text) if end < 0 else end
                continue
        i += 1


def _heredoc_openers(text):
    """Heredoc operators outside strings, comments and substitutions."""
    i, quote = 0, None
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        sub = _substitution_at(text, i)
        if sub:
            i = sub.end
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif text.startswith("<<<", i):
            i += 3
            continue
        elif text.startswith("<<", i):
            opener = _HEREDOC_OPEN_RE.match(text, i)
            if opener:
                yield opener
                i = opener.end()
                continue
        i += 1


def _split_pipeline_statements(text):
    for statement in _split_statements(text):
        yield from _split_pipeline(statement)


def _split_statements(text):
    return _scan_split(text)


def _split_pipeline(text):
    return _scan_split(text, pipes_only=True)


def _scan_split(text, pipes_only=False):
    """Split real operators, leaving strings and nested expansions intact."""
    parts, buf = [], []
    quote, i = None, 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            buf.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i:i + 2])
            i += 2
            continue
        sub = _substitution_at(text, i)
        if sub and (sub.kind in ("$", "`") or quote is None):
            buf.append(text[i:sub.end])
            i = sub.end
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1].isspace()):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        two = text[i:i + 2]
        width = 0
        if pipes_only:
            if two == "||":
                buf.append(two)
                i += 2
                continue
            if ch == "|":
                width = 2 if two == "|&" else 1
        elif two in _TWO_CHAR_OPS:
            width = 2
        elif ch in _STATEMENT_SEPS:
            width = 1
        elif ch == "&" and two != "&>" and (i == 0 or text[i - 1] not in "|>"):
            width = 1
        if width:
            parts.append("".join(buf))
            buf = []
            i += width
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts
