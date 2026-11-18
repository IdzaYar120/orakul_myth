"""Repository paths shared by tests (kept out of conftest so importing it has no side effects)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
