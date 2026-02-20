"""Shared test helpers for PGVectorRAGIndexer test suite."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_PROJECT_ROOT = Path(__file__).parent.parent


def get_alembic_head() -> str:
    """Return current Alembic head revision dynamically.

    Uses project-root-based path so it works regardless of CWD.
    """
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(cfg).get_current_head()
