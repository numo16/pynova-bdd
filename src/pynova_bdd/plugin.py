"""pytest plugin: options, fixtures and hooks for running pytest-bdd steps with Nova Act."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, cast

import pytest

from pynova_bdd import config as _config
from pynova_bdd.auth import build_workflow, resolve_auth
from pynova_bdd.config import NovaConfig
from pynova_bdd.session import ClientFactory, NovaClient, NovaSession

if TYPE_CHECKING:
    from nova_act import NovaAct, Workflow
    from playwright.sync_api import Page
    from pytest_bdd.parser import Feature, Scenario, Step

CURRENT_STEP = pytest.StashKey["Step"]()
_CONFIG_KEY = pytest.StashKey[NovaConfig]()


def pytest_addoption(parser: pytest.Parser) -> None:
    _config.add_options(parser)


def pytest_configure(config: pytest.Config) -> None:
    config.stash[_CONFIG_KEY] = _config.load_config(config)


def pytest_bdd_before_step(
    request: pytest.FixtureRequest,
    feature: Feature,
    scenario: Scenario,
    step: Step,
    step_func: Callable[..., Any],
) -> None:
    # The catch-all steps read the docstring/data table from here.
    request.node.stash[CURRENT_STEP] = step


@pytest.fixture(scope="session")
def nova_config(pytestconfig: pytest.Config) -> NovaConfig:
    """Resolved plugin settings (ini < command line)."""
    return pytestconfig.stash[_CONFIG_KEY]


@pytest.fixture(scope="session")
def nova_workflow(nova_config: NovaConfig) -> Iterator[Workflow]:
    """Session-wide Nova Act ``Workflow`` for IAM auth. Only created when IAM auth is used."""
    with build_workflow(nova_config) as workflow:
        yield workflow


@pytest.fixture(scope="session")
def nova_client_factory(request: pytest.FixtureRequest, nova_config: NovaConfig) -> ClientFactory:
    """Callable that builds an unstarted Nova Act client.

    Override this fixture to customise ``NovaAct`` arguments, or to use
    ``pynova_bdd.testing.FakeNovaAct`` in tests that must not reach the service.
    """

    def factory(**kwargs: Any) -> NovaClient:
        from nova_act import NovaAct

        auth = resolve_auth(nova_config)
        if auth.mode == "iam":
            kwargs["workflow"] = request.getfixturevalue("nova_workflow")
        else:
            kwargs["nova_act_api_key"] = auth.api_key
        return cast(NovaClient, NovaAct(**kwargs))

    return factory


@pytest.fixture
def nova_session(nova_config: NovaConfig, nova_client_factory: ClientFactory) -> Iterator[NovaSession]:
    """The scenario's Nova session; the browser starts on first use and stops at teardown."""
    session = NovaSession(nova_config, nova_client_factory)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def nova(nova_session: NovaSession) -> NovaAct:
    """The started ``NovaAct`` client, for Python steps that call Nova Act directly."""
    return cast("NovaAct", nova_session.client())


@pytest.fixture
def nova_page(nova: NovaAct) -> Page:
    """The Playwright page Nova Act is driving, for deterministic Python steps."""
    return nova.page
