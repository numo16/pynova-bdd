from __future__ import annotations

import json
import textwrap
from typing import Any

import nova_act  # noqa: F401  (import once: numpy cannot be re-imported by in-process pytester runs)
import pytest

# Inner-project conftest: swaps Nova Act for FakeNovaAct and dumps every call to calls.json.
FAKE_CONFTEST = """
import json
import pytest
from pynova_bdd.testing import FakeNovaAct

_FAKE = FakeNovaAct()

@pytest.fixture(scope="session")
def fake_nova():
    return _FAKE

@pytest.fixture(scope="session")
def nova_client_factory(fake_nova):
    return fake_nova.factory

def pytest_sessionfinish(session):
    calls = [
        {
            "method": c.method,
            "argument": c.argument,
            "kwargs": {k: v for k, v in c.kwargs.items() if k != "schema"},
        }
        for c in _FAKE.calls
    ]
    with open("calls.json", "w") as fh:
        json.dump({"calls": calls, "started_with": _FAKE.started_with}, fh)
"""


class NovaProject:
    def __init__(self, pytester: pytest.Pytester) -> None:
        self.pytester = pytester

    def setup(
        self, *, feature: str, test: str | None = None, conftest_extra: str = "", ini: str = ""
    ) -> None:
        self.pytester.makeconftest(FAKE_CONFTEST + textwrap.dedent(conftest_extra))
        self.pytester.makefile(".feature", example=textwrap.dedent(feature))
        self.pytester.makepyfile(
            test_example=textwrap.dedent(test)
            if test is not None
            else 'from pytest_bdd import scenarios\nscenarios("example.feature")\n'
        )
        if ini:
            self.pytester.makeini("[pytest]\n" + textwrap.dedent(ini))

    def run(self, *args: str) -> pytest.RunResult:
        return self.pytester.runpytest("-p", "no:cacheprovider", *args)

    def calls(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads((self.pytester.path / "calls.json").read_text())
        return result

    def methods(self) -> list[tuple[str, str | None]]:
        return [(c["method"], c["argument"]) for c in self.calls()["calls"]]


@pytest.fixture
def project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> NovaProject:
    monkeypatch.delenv("CI", raising=False)
    return NovaProject(pytester)
