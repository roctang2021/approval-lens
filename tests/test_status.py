"""Exercise the status command for every outcome the hook can persist."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import lens as al


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "approval-lens-status.py"


@pytest.mark.parametrize("outcome", al.TIER2_OUTCOMES)
@pytest.mark.parametrize("lang", al.available_langs())
def test_status_renders_every_tier2_outcome(tmp_path, lang, outcome):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"lang": lang, "llm": {"enabled": True}}), encoding="utf-8")
    heartbeat = tmp_path / al.HEARTBEAT_FILE
    heartbeat.write_text(json.dumps({
        "running": al.plugin_version(),
        "last": {"ts": time.time(), "tool": "Bash", "severity": "high", "asked": True},
        "tier2": {"outcome": outcome, "ts": time.time()},
    }), encoding="utf-8")
    env = dict(os.environ, APPROVAL_LENS_CONFIG=str(config),
               APPROVAL_LENS_CACHE_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, str(SCRIPT)], env=env, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    expected = al.ui_text(al.load_locale(lang), "tier2_" + outcome, section="status")
    assert expected and expected in result.stdout
