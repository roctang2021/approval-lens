"""Keep untrusted model text readable without terminal or bidi side effects."""
import pytest

import lens as al
from lens.util import one_line


@pytest.mark.parametrize("control", ["\x1b[2J", "\x07", "\x08", "\x9b31m", "\u202e", "\u2066"])
def test_model_note_controls_are_visible_escapes(control):
    matches = al.analyze_command(al.Parsed("rm -rf /tmp/report"))
    reason = al.render_reason(matches, llm_text=f"Deletes report{control}.txt")
    assert reason.startswith("🔴 ")
    assert control[0] not in reason
    assert f"\\u{ord(control[0]):04x}" in reason


def test_regular_multilingual_text_and_emoji_are_preserved():
    text = "🔴 English 中文 繁體 日本語 español français 👩‍💻"
    assert one_line(text + "\n  next\tline") == text + " next line"
