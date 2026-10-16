"""Run the examples against the real Nova Act service. Skipped without credentials."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (os.environ.get("NOVA_ACT_API_KEY") or os.environ.get("PYNOVA_E2E_IAM")),
        reason="needs NOVA_ACT_API_KEY (or PYNOVA_E2E_IAM=1 with AWS credentials)",
    ),
]


def test_todo_example() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "examples/todo", "-p", "no:cacheprovider", "--nova-headless", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    print(result.stdout[-10000:], result.stderr[-5000:])
    assert result.returncode == 0
