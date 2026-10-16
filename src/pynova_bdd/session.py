"""Per-scenario Nova Act client lifecycle and guarded step execution (docs/DESIGN.md §4.10)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from pynova_bdd import guardrails, prompts
from pynova_bdd.config import NovaConfig
from pynova_bdd.errors import (
    NovaAssertionFailed,
    NovaConfigError,
    NovaStepFailed,
    NovaVerificationError,
    describe_act_error,
)

if TYPE_CHECKING:
    from nova_act import ActError
    from pytest_bdd.parser import Step


class NovaClient(Protocol):
    """The subset of ``nova_act.NovaAct`` the plugin uses."""

    @property
    def page(self) -> Any: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def go_to_url(self, url: str) -> None: ...
    def act(self, prompt: str, **kwargs: Any) -> Any: ...
    def act_get(self, prompt: str, schema: Any = ..., **kwargs: Any) -> Any: ...


ClientFactory = Callable[..., NovaClient]


@dataclasses.dataclass(frozen=True)
class StepRecord:
    """What Nova did for one step; collected on ``NovaSession.results``."""

    step: str
    kind: str  # "navigate", "act" or "verify"
    result: object | None = None
    evidence: tuple[str, ...] = ()


def _datatable_rows(step: Step | None) -> Sequence[Sequence[object]] | None:
    if step is None or step.datatable is None:
        return None
    return step.datatable.raw()


def _parsed(result: Any) -> dict[str, Any] | None:
    parsed = getattr(result, "parsed_response", None)
    if not getattr(result, "matches_schema", False) or not isinstance(parsed, dict):
        return None
    return parsed


class NovaSession:
    """Owns one Nova Act client for a scenario and runs steps through it under guardrails.

    The browser starts lazily, so scenarios whose steps are all Python never launch one.
    """

    def __init__(self, config: NovaConfig, factory: ClientFactory, test_id: str = "") -> None:
        self._config = config
        self._factory = factory
        self._test_id = test_id
        self._client: NovaClient | None = None
        self.fence = guardrails.NavigationFence(config.allowed_origins)
        if config.base_url:
            self.fence.allow(config.base_url)
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
            self.fence.allow(page)
            client = self._factory(
                starting_page=page, headless=self._config.headless, state_guardrail=self.fence
            )
            client.start()
            self._client = client
        return self._client

    def close(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            client.stop()

    def _act_kwargs(self, step_text: str, max_steps: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"max_steps": max_steps}
        if self._config.timeout is not None:
            kwargs["timeout"] = self._config.timeout
        if self._config.model_temperature is not None:
            kwargs["model_temperature"] = self._config.model_temperature
        seed = self._config.model_seed
        if seed == "auto":
            kwargs["model_seed"] = guardrails.derive_seed(self._test_id, step_text)
        elif seed is not None:
            kwargs["model_seed"] = seed
        return kwargs

    def _failed(self, text: str, exc: ActError) -> NovaStepFailed:
        message = describe_act_error(text, exc)
        if self.fence.blocked:
            message += (
                f"\n  Navigation was blocked by the guardrail: {self.fence.blocked[-1]}"
                "\n  (add the origin to nova_allowed_origins if the app really goes there)"
            )
        return NovaStepFailed(message, act_error=exc)

    def navigate(self, url: str) -> None:
        """Go to ``url`` without the model; the URL's origin becomes an allowed origin."""
        __tracebackhide__ = True
        try:
            target = prompts.resolve_url(url, self._config.base_url)
        except ValueError as exc:
            raise NovaConfigError(str(exc)) from None
        self.fence.allow(target)
        if self._client is None:
            self.client(starting_page=target)
        else:
            self._client.go_to_url(target)
        self.results.append(StepRecord(step=url, kind="navigate"))

    def action(self, text: str, step: Step | None = None) -> None:
        """Run a Given/When step under the step contract."""
        __tracebackhide__ = True
        from nova_act import ActError

        url = prompts.navigation_target(text)
        if url is not None:
            self.navigate(url)
            return

        prompt = prompts.action_prompt(text, step.docstring if step else None, _datatable_rows(step))
        client = self.client()
        try:
            result = client.act_get(
                prompt, schema=prompts.ACTION_SCHEMA, **self._act_kwargs(text, self._config.max_steps)
            )
        except ActError as exc:
            raise self._failed(text, exc) from None
        self.results.append(StepRecord(step=text, kind="act", result=result))

        report = _parsed(result)
        if report is None or not isinstance(report.get("completed_as_written"), bool):
            raise NovaStepFailed(
                f"Nova Act did not report whether it completed the step: {text}\n"
                f"  response: {getattr(result, 'response', None)!r}"
            )
        if not report["completed_as_written"] or report.get("deviation"):
            raise NovaStepFailed(
                f"Nova Act could not do the step exactly as written: {text}\n"
                f"  deviation: {report.get('deviation') or '(none given)'}"
            )

    def verify(self, text: str, step: Step | None = None) -> None:
        """Run a Then step as a read-only, grounded true/false check."""
        __tracebackhide__ = True
        from nova_act import ActError

        if self._config.then_mode == "act":
            self.action(text, step)
            return

        prompt = prompts.verify_prompt(text, step.docstring if step else None, _datatable_rows(step))
        client = self.client()
        before = guardrails.PageFingerprint.capture(client.page)
        self.fence.locked_url = before.url
        try:
            result = client.act_get(
                prompt,
                schema=prompts.VERIFY_SCHEMA,
                **self._act_kwargs(text, self._config.verify_max_steps),
            )
        except ActError as exc:
            raise self._failed(text, exc) from None
        finally:
            self.fence.locked_url = None
        after = guardrails.PageFingerprint.capture(client.page)

        verdict = _parsed(result)
        evidence = verdict.get("evidence") if verdict else None
        quotes = tuple(str(q) for q in evidence) if isinstance(evidence, list) else ()
        self.results.append(StepRecord(step=text, kind="verify", result=result, evidence=quotes))

        # Layer 3: a check that changed the page proves nothing, whatever it concluded.
        if self._config.readonly_check:
            changes = before.differences(after)
            if changes:
                raise NovaVerificationError(
                    f"The check modified the page, so its verdict is not trusted: {text}\n"
                    f"  {'; '.join(changes)}"
                )

        # Layer 4: only a grounded, explicit "true" passes.
        if verdict is None or verdict.get("verdict") not in ("true", "false", "unsure"):
            raise NovaVerificationError(
                f"Nova Act did not return a verdict for: {text}\n"
                f"  response: {getattr(result, 'response', None)!r}"
            )
        shown = "; ".join(quotes) or "(no evidence given)"
        if verdict["verdict"] == "false":
            raise NovaAssertionFailed(f"{text}\n  Nova Act found this to be false: {shown}")
        if verdict["verdict"] == "unsure":
            raise NovaAssertionFailed(f"{text}\n  Nova Act could not confirm this (unsure): {shown}")

        if not quotes:
            raise NovaVerificationError(f"Nova Act said true but quoted no page text as evidence: {text}")
        ungrounded = guardrails.ungrounded_quotes(quotes, after.text)
        if ungrounded:
            raise NovaVerificationError(
                f"Nova Act's evidence is not on the page, so the verdict is not trusted: {text}\n"
                f"  not found: {ungrounded!r}"
            )
        if self._config.literal_check:
            missing = guardrails.ungrounded_quotes(guardrails.literal_expectations(text), after.text)
            if missing:
                raise NovaAssertionFailed(f"{text}\n  Quoted text not found on the page: {missing!r}")
