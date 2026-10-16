"""Per-scenario Nova Act client lifecycle and step execution."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from pynova_bdd import prompts
from pynova_bdd.config import NovaConfig
from pynova_bdd.errors import (
    NovaAssertionFailed,
    NovaConfigError,
    NovaStepFailed,
    NovaVerificationError,
    describe_act_error,
)

if TYPE_CHECKING:
    from nova_act import ActResult
    from pytest_bdd.parser import Step


class NovaClient(Protocol):
    """The subset of ``nova_act.NovaAct`` the plugin uses."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def go_to_url(self, url: str) -> None: ...
    def act(self, prompt: str, **kwargs: Any) -> ActResult: ...
    def act_get(self, prompt: str, schema: Any = ..., **kwargs: Any) -> Any: ...


ClientFactory = Callable[..., NovaClient]


@dataclasses.dataclass(frozen=True)
class StepRecord:
    """What Nova did for one step; collected on ``NovaSession.results``."""

    step: str
    kind: str  # "navigate", "act" or "verify"
    result: object | None = None


def _datatable_rows(step: Step | None) -> Sequence[Sequence[object]] | None:
    if step is None or step.datatable is None:
        return None
    return step.datatable.raw()


class NovaSession:
    """Owns one Nova Act client for a scenario and runs steps through it.

    The browser starts lazily, so scenarios whose steps are all Python never launch one.
    """

    def __init__(self, config: NovaConfig, factory: ClientFactory) -> None:
        self._config = config
        self._factory = factory
        self._client: NovaClient | None = None
        self.results: list[StepRecord] = []

    @property
    def started(self) -> bool:
        return self._client is not None

    def client(self, starting_page: str | None = None) -> NovaClient:
        """Return the started client, starting it on ``starting_page`` or ``nova_base_url``."""
        if self._client is None:
            page = starting_page or self._config.base_url
            if not page:
                raise NovaConfigError(
                    "Nova Act needs a starting page: set nova_base_url, or begin the scenario with a step "
                    'such as: Given I am on "https://example.com"'
                )
            client = self._factory(starting_page=page, headless=self._config.headless)
            client.start()
            self._client = client
        return self._client

    def close(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            client.stop()

    def _act_kwargs(self) -> dict[str, int]:
        kwargs: dict[str, int] = {}
        if self._config.max_steps is not None:
            kwargs["max_steps"] = self._config.max_steps
        if self._config.timeout is not None:
            kwargs["timeout"] = self._config.timeout
        return kwargs

    def navigate(self, url: str) -> None:
        __tracebackhide__ = True
        try:
            target = prompts.resolve_url(url, self._config.base_url)
        except ValueError as exc:
            raise NovaConfigError(str(exc)) from None
        if self._client is None:
            self.client(starting_page=target)
        else:
            self._client.go_to_url(target)
        self.results.append(StepRecord(step=url, kind="navigate"))

    def action(self, text: str, step: Step | None = None) -> None:
        """Run a Given/When step: navigate directly when it is a plain URL, otherwise ``act()``."""
        __tracebackhide__ = True
        from nova_act import ActError

        url = prompts.navigation_target(text)
        if url is not None:
            self.navigate(url)
            return

        prompt = prompts.action_prompt(text, step.docstring if step else None, _datatable_rows(step))
        client = self.client()
        try:
            result = client.act(prompt, **self._act_kwargs())
        except ActError as exc:
            raise NovaStepFailed(describe_act_error(text, exc), act_error=exc) from None
        self.results.append(StepRecord(step=text, kind="act", result=result))

    def verify(self, text: str, step: Step | None = None) -> None:
        """Run a Then step as a yes/no check that passes or fails the test."""
        __tracebackhide__ = True
        from nova_act import ActError

        if self._config.then_mode == "act":
            self.action(text, step)
            return

        prompt = prompts.verify_prompt(text, step.docstring if step else None, _datatable_rows(step))
        client = self.client()
        try:
            result = client.act_get(prompt, schema=prompts.VERIFY_SCHEMA, **self._act_kwargs())
        except ActError as exc:
            raise NovaStepFailed(describe_act_error(text, exc), act_error=exc) from None
        self.results.append(StepRecord(step=text, kind="verify", result=result))

        verdict = getattr(result, "parsed_response", None)
        if not getattr(result, "matches_schema", False) or not isinstance(verdict, dict):
            raise NovaVerificationError(
                f"Nova Act did not return a yes/no verdict for: {text}\n"
                f"  response: {getattr(result, 'response', None)!r}"
            )
        passed = verdict.get("passed")
        if passed is True:
            return
        evidence = verdict.get("evidence") or "(no evidence given)"
        if passed is False:
            raise NovaAssertionFailed(f"{text}\n  Nova Act found this to be false: {evidence}")
        raise NovaVerificationError(
            f"Nova Act returned an invalid verdict for: {text}\n  verdict: {verdict!r}"
        )
