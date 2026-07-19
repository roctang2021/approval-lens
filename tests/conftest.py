"""Shared pytest fixtures / path setup for the Permission Lens test suite."""
import sys
from pathlib import Path

import yaml
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

# Make hooks/permission_lens.py importable as `permission_lens`.
sys.path.insert(0, str(HOOKS_DIR))


def _load_corpus(name):
    with open(CORPUS_DIR / name, "r", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("commands", [])


@pytest.fixture(scope="session")
def dangerous_corpus():
    return _load_corpus("dangerous.yaml")


@pytest.fixture(scope="session")
def benign_corpus():
    return _load_corpus("benign.yaml")


def pytest_configure():
    # Expose corpora as module-level constants for parametrization at collection time.
    pytest.DANGEROUS = _load_corpus("dangerous.yaml")
    pytest.BENIGN = _load_corpus("benign.yaml")
