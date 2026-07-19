"""Output-contract tests: on every code path the script prints exactly one JSON
object to stdout and exits 0. Exit 2 on PermissionRequest would DENY, so the
'always exit 0' guarantee is a hard correctness requirement, not a nicety."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "permission_lens.py"


# One shared scratch cache dir for all subprocess runs; the TemporaryDirectory
# finalizer removes it when the test process exits.
_CACHE_TMP = tempfile.TemporaryDirectory(prefix="pl-test-cache-")


def _run(stdin_bytes, env_overrides=None):
    # Run with the same interpreter pytest runs under (has pyyaml), not nested uv.
    # Hermetic: hard-assign config/cache paths so neither the developer's real
    # ~/.config nor ambient PERMISSION_LENS_* exports can leak in (a local
    # config with llm.enabled plus a real API key would otherwise go live).
    env = dict(os.environ)
    env["PERMISSION_LENS_CONFIG"] = "/nonexistent/permission-lens-test.json"
    env["PERMISSION_LENS_CACHE_DIR"] = _CACHE_TMP.name
    env.update(env_overrides or {})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        env=env,
    )
    return proc


def _assert_single_json_object(proc):
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    out = proc.stdout.decode("utf-8")
    # Exactly one JSON object: json.loads over the whole (stripped) stdout succeeds
    # and yields a dict. Any stray non-JSON output would break this.
    parsed = json.loads(out.strip())
    assert isinstance(parsed, dict)
    return parsed


CASES = {
    "valid_bash": json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}),
    "empty_stdin": "",
    "whitespace_stdin": "   \n  ",
    "malformed_json": "this is not json {{{",
    "json_not_object": "[1, 2, 3]",
    "non_bash_tool": json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/x"}}),
    "missing_tool_input": json.dumps({"tool_name": "Bash"}),
    "empty_command": json.dumps({"tool_name": "Bash", "tool_input": {"command": "   "}}),
    "null_command": json.dumps({"tool_name": "Bash", "tool_input": {"command": None}}),
    "unicode_command": json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo 你好 | grep 好"}}),
    "huge_command": json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo " + "A" * 100_000}}),
    "weird_nesting": json.dumps({"tool_name": "Bash", "tool_input": {"command": "$(`curl x`) <(bash)"}}),
}


@pytest.mark.parametrize("name", list(CASES), ids=list(CASES))
def test_stdout_is_single_json_object_and_exit_zero(name):
    proc = _run(CASES[name].encode("utf-8"))
    _assert_single_json_object(proc)


def test_binary_garbage_stdin_fails_open():
    proc = _run(b"\x00\x01\x02\xff\xfe not utf8 \x80")
    _assert_single_json_object(proc)


def test_annotation_present_for_dangerous_command():
    proc = _run(CASES["valid_bash"].encode("utf-8"))
    parsed = _assert_single_json_object(proc)
    assert "systemMessage" in parsed
    # Critically: never a decision field — the native dialog must still show.
    assert "hookSpecificOutput" not in parsed
    assert "decision" not in parsed


def test_message_within_10k_cap():
    proc = _run(CASES["huge_command"].encode("utf-8"))
    parsed = _assert_single_json_object(proc)
    assert len(parsed.get("systemMessage", "")) <= 10_000


def test_llm_enabled_without_key_still_fails_open():
    # Tier 2 opted in but the key env var is unset: the hook must degrade to the
    # Tier 1 message — single JSON object, exit 0, no decision, no network hang.
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        # Point BOTH credential env names at unset vars — otherwise a real
        # ANTHROPIC_AUTH_TOKEN in the developer's shell would make this go live.
        config_path.write_text(json.dumps({
            "llm": {"enabled": True,
                    "api_key_env": "PERMISSION_LENS_NO_SUCH_KEY",
                    "auth_token_env": "PERMISSION_LENS_NO_SUCH_TOKEN"},
        }), encoding="utf-8")
        proc = _run(
            CASES["valid_bash"].encode("utf-8"),
            env_overrides={"PERMISSION_LENS_CONFIG": str(config_path)},
        )
    parsed = _assert_single_json_object(proc)
    assert "systemMessage" in parsed
    assert "hookSpecificOutput" not in parsed


def test_broken_config_file_still_fails_open():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        config_path.write_text("{{{ definitely not json", encoding="utf-8")
        proc = _run(
            CASES["valid_bash"].encode("utf-8"),
            env_overrides={"PERMISSION_LENS_CONFIG": str(config_path)},
        )
    parsed = _assert_single_json_object(proc)
    assert "systemMessage" in parsed
