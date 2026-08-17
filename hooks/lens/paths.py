"""Where the package's data files live.

Resolved once, here, because the code moved into a subpackage while rules.yaml
and locales/ stayed beside the hook entry point — every `Path(__file__)` in a
submodule would otherwise be off by one directory."""
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = HOOKS_DIR.parent

RULES_PATH = HOOKS_DIR / "rules.yaml"            # Bash
WEB_RULES_PATH = HOOKS_DIR / "rules_web.yaml"    # WebFetch (URL)
PATH_RULES_PATH = HOOKS_DIR / "rules_path.yaml"  # Write / Edit
LOCALES_DIR = HOOKS_DIR / "locales"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
