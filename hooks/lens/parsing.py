"""A conservative structural view of a shell command string.

Not a bash grammar: enough structure to tell code from text, which is the line
every false positive and every bypass in this project has turned on."""
import os
import re
import shlex

# ── command parsing (conservative; not a full bash grammar) ───────────────────

# Top-level statement separators and pipeline separators. We split with a
# quote-aware scanner rather than a regex so quoted separators are ignored.
_STATEMENT_SEPS = {";", "\n"}
_TWO_CHAR_OPS = {"&&", "||"}


# A heredoc body is DATA, not shell: `cat >> NOTES.md <<'EOF' … EOF` writes
# prose, `python3 - <<'PY' … PY` runs Python. Statements split on newlines, so
# without this every line of that payload was parsed as its own command — a
# documentation line starting with the word `mkfs` became an `mkfs` invocation
# (found 2026-07-25: writing release notes *about* dangerous commands set off
# 🔴 every time). The exception is a heredoc fed to a shell, whose body really
# is shell code and must stay analyzed.
_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
# `ssh host <<EOF` is not an exception to this: the body is shell source, it
# just runs on the far end. Dropping it as data meant `ssh host <<EOF; rm -rf /;
# EOF` analyzed as nothing at all (found in review 2026-08-14).
_SHELL_INTERPRETERS = ("bash", "sh", "zsh", "dash", "ksh", "fish", "ssh")


def _strip_heredoc_payloads(command):
    """Drop heredoc bodies whose receiving command is not a shell."""
    if "<<" not in command:
        return command
    kept, lines = [], command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        opener = _HEREDOC_OPEN_RE.search(line)
        if not opener:
            continue
        # `bash <<EOF` executes its body; `cat`/`python3`/`tee` do not.
        head = os.path.basename((line.split("<<", 1)[0].split() or [""])[0])
        feeds_shell = head in _SHELL_INTERPRETERS or any(
            os.path.basename(tok) in _SHELL_INTERPRETERS
            for tok in line.split("<<", 1)[0].split())
        delimiter = opener.group(2)
        while i < len(lines) and lines[i].strip() != delimiter:
            if feeds_shell:
                kept.append(lines[i])
            i += 1
        if i < len(lines):  # the delimiter line itself is not data
            i += 1
    return "\n".join(kept)


class Parsed:
    """Best-effort structural view of a shell command string."""

    def __init__(self, command):
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
        for chunk in _iter_command_chunks(self.code):
            for stage in _split_pipeline(chunk):
                stage = stage.strip()
                if stage:
                    self.stages.append(stage)
                    self.simple_commands.append(SimpleCommand(stage))



class SimpleCommand:
    """A single pipeline stage tokenized best-effort into argv."""

    def __init__(self, raw):
        self.raw = raw
        try:
            # posix=True expands quotes but keeps $VAR text literally, which is
            # what we want for target-risk analysis.
            self.argv = shlex.split(raw, posix=True)
        except ValueError:
            self.argv = raw.split()
        # Skip leading `VAR=value` assignments and env/wrappers to find the verb.
        self.name = ""
        for tok in self.argv:
            if "=" in tok and re.match(r"^\w+=", tok):
                continue
            self.name = os.path.basename(tok)
            break

    def redirect_targets(self):
        """Files this stage writes to via > or >>, found quote-aware.

        Structural, not textual: in `echo "add this >> ~/.zshrc"` the operator
        sits INSIDE a quoted argument and is therefore not a redirect at all,
        while `echo 'payload' >> ~/.zshrc` really does append to the file. A
        regex over the raw text cannot tell those apart; this can.
        """
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
        """argv entries that could plausibly BE a path.

        A token containing whitespace is prose that happens to mention a path —
        `git commit -m "fix .env loading"` is a commit message, not a read of
        .env, and it used to fire the credential rule every time.
        """
        return [tok for tok in self.argv if tok and not any(c.isspace() for c in tok)]

    def flags_and_args(self):
        """argv after the command name, split into (flag tokens, positional args)."""
        seen_name = False
        flags, args = [], []
        for tok in self.argv:
            if not seen_name:
                if "=" in tok and re.match(r"^\w+=", tok):
                    continue
                seen_name = True
                continue
            (flags if tok.startswith("-") else args).append(tok)
        return flags, args


def _iter_command_chunks(command):
    """Yield the top-level statement text plus any substitution bodies.

    Substitution bodies are extracted with tolerant regexes and yielded so their
    inner commands get parsed as ordinary statements.
    """
    yield from _split_statements(command)
    for body in re.findall(r"\$\(([^()]*)\)", command):
        yield from _split_statements(body)
    for body in re.findall(r"`([^`]*)`", command):
        yield from _split_statements(body)
    for body in re.findall(r"[<>]\(([^()]*)\)", command):
        yield from _split_statements(body)


def _split_statements(text):
    """Quote-aware split on ; & newline && ||. Returns a list of statement strings."""
    return _scan_split(text, split_pipe=False)


def _split_pipeline(text):
    """Quote-aware split of one statement into pipeline stages on `|`."""
    return _scan_split(text, split_pipe=True, pipes_only=True)


def _scan_split(text, split_pipe=False, pipes_only=False):
    parts = []
    buf = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
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
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        two = text[i:i + 2]
        if pipes_only:
            # Split on a single | but not || (that's a statement separator).
            if ch == "|" and two != "||":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        else:
            if two in _TWO_CHAR_OPS:
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch in _STATEMENT_SEPS or ch == "&":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts
