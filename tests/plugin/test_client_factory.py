"""The default client factory: real NovaAct construction with each auth mode (NovaAct itself stubbed)."""

from __future__ import annotations

import json
import textwrap

import pytest

STUB_CONFTEST = """
import json
import pytest
import nova_act
from pynova_bdd.testing import FakeNovaAct

_FAKE = FakeNovaAct()
_KWARGS = []

def _novaact(**kwargs):
    _KWARGS.append({k: (v if isinstance(v, (str, bool, type(None))) else repr(v)) for k, v in kwargs.items()})
    return _FAKE.factory(**kwargs)

@pytest.fixture(autouse=True)
def stub_novaact(monkeypatch):
    monkeypatch.setattr(nova_act, "NovaAct", _novaact)

@pytest.fixture(scope="session")
def nova_workflow():
    yield "WORKFLOW"

def pytest_sessionfinish(session):
    with open("kwargs.json", "w") as fh:
        json.dump(_KWARGS, fh)
"""

FEATURE = """
Feature: Auth
  Scenario: Go
    Given I am on "https://shop.example.com"
"""


@pytest.fixture
def stub_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("NOVA_ACT_API_KEY", raising=False)
    pytester.makeconftest(STUB_CONFTEST)
    pytester.makefile(".feature", example=textwrap.dedent(FEATURE))
    pytester.makepyfile(test_example='from pytest_bdd import scenarios\nscenarios("example.feature")\n')
    return pytester


def test_api_key_auth(stub_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_ACT_API_KEY", "secret-key")
    stub_project.runpytest().assert_outcomes(passed=1)
    kwargs = json.loads((stub_project.path / "kwargs.json").read_text())
    assert kwargs == [
        {"starting_page": "https://shop.example.com", "headless": False, "nova_act_api_key": "secret-key"}
    ]


def test_iam_auth_uses_session_workflow(stub_project: pytest.Pytester) -> None:
    stub_project.makeini("[pytest]\nnova_auth = iam\nnova_workflow_definition = suite\n")
    stub_project.runpytest().assert_outcomes(passed=1)
    kwargs = json.loads((stub_project.path / "kwargs.json").read_text())
    assert kwargs == [
        {"starting_page": "https://shop.example.com", "headless": False, "workflow": "WORKFLOW"}
    ]


def test_missing_credentials_fail_on_first_nova_step(stub_project: pytest.Pytester) -> None:
    stub_project.makeini("[pytest]\nnova_auth = api_key\n")
    result = stub_project.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaConfigError: nova_auth is 'api_key' but NOVA_ACT_API_KEY is not set*"])
