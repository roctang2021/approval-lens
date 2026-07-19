"""Tier 1 latency budget: analysis must stay well under 50ms per command.

Measures the in-process analysis (parse + rule evaluation + format) after import,
matching the brief's 'Tier 1 <=50ms' requirement. Process/uv startup is excluded
because that is amortized by uv's env cache and is not the analyzer's cost."""
import sys
import time
from pathlib import Path

import yaml

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
sys.path.insert(0, str(HOOKS_DIR))

import permission_lens as pl  # noqa: E402


def _all_commands():
    cmds = []
    for name in ("dangerous.yaml", "benign.yaml"):
        with open(CORPUS_DIR / name, "r", encoding="utf-8") as fh:
            cmds += [e["command"] for e in (yaml.safe_load(fh) or {}).get("commands", [])]
    return cmds


def _analyze_once(command):
    parsed = pl.Parsed(command)
    matches = pl.analyze(parsed)
    pl.format_message(parsed, matches)


def test_each_command_under_50ms():
    pl.load_rules()  # warm the rule cache (one-time YAML load, excluded from budget)
    slow = []
    for command in _all_commands():
        # best-of-3 to smooth scheduler jitter on shared CI runners
        best = min(_time_once(command) for _ in range(3))
        if best > 0.050:
            slow.append((command, best))
    assert not slow, "commands exceeding 50ms: " + ", ".join(f"{c} ({t*1000:.1f}ms)" for c, t in slow)


def test_corpus_average_well_under_budget():
    pl.load_rules()
    commands = _all_commands()
    start = time.perf_counter()
    for command in commands:
        _analyze_once(command)
    avg = (time.perf_counter() - start) / len(commands)
    assert avg < 0.010, f"average {avg*1000:.2f}ms/command exceeds 10ms"


def _time_once(command):
    start = time.perf_counter()
    _analyze_once(command)
    return time.perf_counter() - start
