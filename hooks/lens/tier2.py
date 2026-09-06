"""Optional Anthropic model notes with a local response cache.

Failures return a result without text; offline rule explanations remain available."""
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import traceback
from collections import namedtuple

from .context import task_context
from .locales import BASE_LANG, load_locale, ui_text
from .util import cache_dir, log_debug, one_line

# Use stdlib HTTP to avoid an SDK dependency in the hook.

# This provider uses an Anthropic API key, independently of the host login.
LLM_API_URL = "https://api.anthropic.com/v1/messages"
LLM_API_VERSION = "2023-06-01"
LLM_MAX_TOKENS = 300
# Dialogs show short subjects; skip Tier 2 for pathological inputs.
LLM_MAX_COMMAND_CHARS = 4000

# Select the localized system prompt by subject kind.
LLM_PROMPT_KINDS = ("bash", "url", "path")


# Per-call outcomes feed the heartbeat and status command.
TIER2_OUTCOMES = ("off", "skipped", "cached", "no_credential", "empty", "ok",
                  "filtered", "error")

Tier2Result = namedtuple("Tier2Result", "text outcome")
TIER2_OFF = Tier2Result(None, "off")

_GUARD_CACHE = {}


def _reject_patterns(lang):
    """Compiled patterns whose presence disqualifies a Tier 2 sentence."""
    if lang not in _GUARD_CACHE:
        raw = (load_locale(lang).get("llm_guard") or {}).get("reject") or []
        compiled = []
        for pattern in raw:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                log_debug("llm_guard: bad pattern %r in %s" % (pattern, lang))
        _GUARD_CACHE[lang] = tuple(compiled)
    return _GUARD_CACHE[lang]


def is_safety_verdict(text, lang):
    """Match known safety verdicts and approval advice in generated text.

    This pattern filter is partial: it cannot guarantee factual accuracy or
    catch every instruction hidden in the model input."""
    return any(pattern.search(text) for pattern in _reject_patterns(lang))


def tier2_explanation(subject, config, kind="bash", event=None):
    """Return a model note and its status using a validated config.

    Send the subject and, when opted in, the latest user request. The result
    may supplement the reason but does not determine severity or confirmation."""
    llm = config["llm"]
    if not llm["enabled"]:
        return TIER2_OFF
    try:
        if not subject or len(subject) > LLM_MAX_COMMAND_CHARS:
            return Tier2Result(None, "skipped")
        if kind not in LLM_PROMPT_KINDS:
            kind = "bash"
        model, lang = llm["model"], config["lang"]
        task = task_context(event) if (event and llm["send_task_context"]) else ""
        ttl_days = llm["cache_ttl_days"]
        # The task is part of the cache key: the same command under a different
        # request deserves a different answer.
        cache_path = _llm_cache_path(subject, model, lang, kind, task)
        cached = _cache_lookup(cache_path, ttl_days)
        if cached is not None:
            cached = one_line(cached)
            if cached and is_safety_verdict(cached, lang):
                return Tier2Result(None, "filtered")
            return Tier2Result(cached or None, "cached")
        credential = _resolve_credential(llm)
        if credential is None:
            # GUI-launched hosts may not inherit shell exports.
            return Tier2Result(None, "no_credential")
        timeout = llm["timeout_seconds"]
        text = _run_with_deadline(
            lambda: _post_messages_api(subject, model, lang, kind, credential,
                                       timeout, task),
            timeout,
        )
        text = one_line(text or "")
        if not text:
            return Tier2Result(None, "empty")  # deadline, non-2xx, unparseable
        if ttl_days > 0:  # do not store responses when caching is disabled
            _cache_store(cache_path, text)
            # Keep filtered responses cached to avoid repeated requests; recheck
            # them on reads so new filters also apply to old responses.
        if is_safety_verdict(text, lang):
            return Tier2Result(None, "filtered")
        return Tier2Result(text, "ok")
    except Exception:
        log_debug("tier2: " + traceback.format_exc())
        return Tier2Result(None, "error")


def _read_credential_file(path):
    """Read the first non-comment, nonempty key line, or return an empty string."""
    if not path:
        return ""
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except FileNotFoundError:
        pass  # an unconfigured credential file is the normal case
    except Exception:
        # The path, never the contents — this function handles secrets.
        log_debug("credential file %s unreadable: %s" % (path, traceback.format_exc()))
    return ""


def _resolve_credential(llm):
    """Resolve an API key from the configured environment variable, then file."""
    api_key = os.environ.get(llm.get("api_key_env") or "", "").strip()
    if api_key:
        return api_key
    return _read_credential_file(llm.get("api_key_file")) or None


def _post_messages_api(subject, model, lang, kind, api_key, timeout, task=""):
    # Lazy import keeps Tier 1 startup lean (urllib.request pulls in a lot).
    import urllib.request

    system = _llm_system_prompt(lang, kind, bool(task))
    # The request contains the prompt, subject and opted-in task context.
    # It does not automatically attach other event fields or transcript records.
    if task:
        content = (f"<user_request>\n{task}\n</user_request>\n"
                   f"<operation>\n{subject}\n</operation>")
    else:
        content = subject
    body = json.dumps({
        "model": model,
        "max_tokens": LLM_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "anthropic-version": LLM_API_VERSION,
        "x-api-key": api_key,
    }
    req = urllib.request.Request(LLM_API_URL, data=body, headers=headers, method="POST")
    # Socket-level timeout; the wall-clock cap is enforced by _run_with_deadline.
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for block in data.get("content", []):
        if block.get("type") == "text" and str(block.get("text", "")).strip():
            return str(block["text"]).strip()
    return None


def _run_with_deadline(fn, seconds):
    """Limit the caller's wait for a model response.

    A socket timeout applies per operation. The daemon worker bounds total
    waiting time but may continue its request after the caller falls back."""
    box = {}

    def worker():
        try:
            box["value"] = fn()
        except Exception:
            log_debug("tier2 fetch: " + traceback.format_exc())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(seconds)
    return box.get("value")


def _llm_system_prompt(lang, kind, with_task=False):
    """The exact system prompt a request would carry, prompt + optional suffix."""
    system = ui_text(load_locale(lang), kind, "", section="llm_prompts") or ui_text(
        load_locale(BASE_LANG), "bash", "", section="llm_prompts")
    if with_task:
        system += " " + (ui_text(load_locale(lang), "task_suffix", "", section="llm_prompts")
                         or ui_text(load_locale(BASE_LANG), "task_suffix", "",
                                    section="llm_prompts"))
    return system


def _llm_cache_path(subject, model, lang, kind="bash", task=""):
    # Include the prompt in the key so prompt edits invalidate cached answers.
    prompt = _llm_system_prompt(lang, kind, bool(task))
    digest = hashlib.sha256(
        f"{model}\n{lang}\n{kind}\n{task}\n{prompt}\n{subject}".encode("utf-8")).hexdigest()
    return cache_dir() / "llm" / f"{digest}.json"


def _cache_lookup(path, ttl_days):
    if ttl_days <= 0:
        return None
    try:
        # Older versions created this directory with the user's default umask.
        path.parent.chmod(0o700)
        with open(path, "r", encoding="utf-8") as fh:
            entry = json.load(fh)
        text, created = entry.get("text"), entry.get("created")
        if not isinstance(text, str) or isinstance(created, bool) \
                or not isinstance(created, (int, float)):
            return None
        # Future and non-finite timestamps must not extend cache lifetime.
        if not 0 <= time.time() - created <= ttl_days * 86400:
            return None
        return text
    except FileNotFoundError:
        return None  # a cache miss is the normal case
    except Exception:
        log_debug("cache entry %s unreadable: %s" % (path, traceback.format_exc()))
        return None  # corrupt entry -> treat as a miss


def _cache_store(path, text):
    tmp = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        # Responses may repeat sensitive inputs. Secure creation also avoids
        # following a pre-existing temporary file or symlink.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, prefix=path.name + ".",
                                         suffix=".tmp", delete=False) as fh:
            tmp = fh.name
            json.dump({"text": text, "created": time.time()}, fh, ensure_ascii=False)
        os.replace(tmp, path)  # atomic on POSIX; concurrent hooks can't corrupt
    except Exception:
        # cache is best-effort only; don't leave a half-written tmp behind
        if tmp is not None:
            try:
                os.unlink(tmp)
            except Exception:
                pass
