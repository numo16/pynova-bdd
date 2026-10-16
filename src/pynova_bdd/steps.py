"""Catch-all step definitions that send unmatched Gherkin steps to Nova Act.

This module is registered as its own pytest plugin (entry point ``nova_bdd_steps``) so its step
fixtures sit at the root scope. pytest-bdd prefers the most specific step definition, so any step a
user defines in a test module or conftest wins over these (docs/DESIGN.md §4.2).
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, then, when
from pytest_bdd.exceptions import StepDefinitionNotFoundError

from pynova_bdd.config import NovaConfig
from pynova_bdd.plugin import CURRENT_STEP
from pynova_bdd.session import NovaSession

_ANY = parsers.re(r"(?P<instruction>.+)")


def _session_or_fail(request: pytest.FixtureRequest, keyword: str, instruction: str) -> NovaSession:
    __tracebackhide__ = True
    config: NovaConfig = request.getfixturevalue("nova_config")
    if not config.enabled:
        raise StepDefinitionNotFoundError(
            f"Step definition is not found: {keyword} {instruction!r} (Nova Act is disabled by --no-nova or "
            "nova_enabled=false)."
        )
    session: NovaSession = request.getfixturevalue("nova_session")
    return session


@given(_ANY)
def nova_given(instruction: str, request: pytest.FixtureRequest) -> None:
    __tracebackhide__ = True
    _session_or_fail(request, "Given", instruction).action(
        instruction, request.node.stash.get(CURRENT_STEP, None)
    )


@when(_ANY)
def nova_when(instruction: str, request: pytest.FixtureRequest) -> None:
    __tracebackhide__ = True
    _session_or_fail(request, "When", instruction).action(
        instruction, request.node.stash.get(CURRENT_STEP, None)
    )


@then(_ANY)
def nova_then(instruction: str, request: pytest.FixtureRequest) -> None:
    __tracebackhide__ = True
    _session_or_fail(request, "Then", instruction).verify(
        instruction, request.node.stash.get(CURRENT_STEP, None)
    )
