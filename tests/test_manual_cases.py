"""The checklist must agree with the rules it is supposed to exercise.

Written after a rule change silently invalidated a case: `dd of=/dev/null` was
section 1's deliberately-harmless 🔴 probe, and excluding pseudo-devices from
dd-to-device (correctly) made it match nothing — so the checklist went on
promising a red dialog that could no longer appear. The owner caught it by eye.
A checklist that has drifted from the rules is worse than none: every miss it
produces reads as a plugin bug.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

import lens as pl  # noqa: E402

DOC = ROOT / "scripts" / "manual-test-cases.md"
EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def _section(name, upto):
    text = DOC.read_text(encoding="utf-8")
    return text[text.index(f"## {name}、"):text.index(f"## {upto}、")]


def _rows(body, pattern):
    for line in body.splitlines():
        m = re.match(pattern, line)
        if m:
            yield m.group(1).replace("\\|", "|"), m


def _severity(command):
    hits = pl.analyze(pl.Parsed(command))
    return hits[0]["severity"] if hits else None


CMD_ROW = r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|"
# Section 3 is a numbered list, not a table. Parsing it with the table pattern
# matched zero rows and every assertion below passed vacuously — which is why
# test_sections_are_not_empty exists.
LIST_ROW = r"\s*\d+\.\s*`([^`]+)`"
SEV_ROW = r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*(🔴|🟡|🟢)"


def _ids(cases):
    return [c[0] for c in cases]


SECTION_1 = list(_rows(_section("一", "二"), CMD_ROW))
SECTION_2 = list(_rows(_section("二", "三"), SEV_ROW))
SECTION_3 = list(_rows(_section("三", "四"), LIST_ROW))


def test_sections_are_not_empty():
    """A parser that silently matches nothing would make every test below pass."""
    assert len(SECTION_1) >= 10 and len(SECTION_2) >= 20 and len(SECTION_3) >= 30


@pytest.mark.parametrize("command,_m", SECTION_1, ids=_ids(SECTION_1))
def test_section_1_cases_are_high(command, _m):
    assert _severity(command) == "high", f"{command} is no longer 🔴"


@pytest.mark.parametrize("command,m", SECTION_2, ids=_ids(SECTION_2))
def test_section_2_severity_matches_the_table(command, m):
    got = _severity(command)
    assert EMOJI.get(got) == m.group(2), f"{command} -> {got}"


@pytest.mark.parametrize("command,_m", SECTION_3, ids=_ids(SECTION_3))
def test_section_3_cases_stay_silent(command, _m):
    hits = [h["id"] for h in pl.analyze(pl.Parsed(command))]
    assert hits == [], f"{command} now fires {hits}"
