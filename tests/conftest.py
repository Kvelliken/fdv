from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROT / "src"))
sys.path.insert(0, str(ROT / "tests"))

from kostra_fdv import les_konfig  # noqa: E402


@pytest.fixture(scope="session")
def konfig() -> dict:
    return les_konfig(ROT / "config.yaml")


@pytest.fixture(scope="session")
def repo_rot() -> Path:
    return ROT
