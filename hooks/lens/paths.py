"""Data paths resolved relative to the installed package."""
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = HOOKS_DIR.parent

RULES_PATH = HOOKS_DIR / "rules.yaml"            # Bash
WEB_RULES_PATH = HOOKS_DIR / "rules_web.yaml"    # WebFetch (URL)
PATH_RULES_PATH = HOOKS_DIR / "rules_path.yaml"  # Write / Edit
LOCALES_DIR = HOOKS_DIR / "locales"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
