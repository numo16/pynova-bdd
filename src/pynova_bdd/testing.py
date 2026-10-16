"""Offline test double for Nova Act.

Use it to test the plugin, or your own feature files, without a browser or credentials::

    # conftest.py
    import pytest
    from pynova_bdd.testing import FakeNovaAct

    @pytest.fixture(scope="session")
    def fake_nova():
        return FakeNovaAct()

    @pytest.fixture(scope="session")
    def nova_client_factory(fake_nova):
        return fake_nova.factory

Rules let a test script the agent, including an agent that misbehaves, which is how the guardrails
are tested::

    fake.fail_when("cart shows 3 items")                  # Then step answers "false"
    fake.on("add to cart", ActAgentFailed("no button"))   # act raises
    fake.on("cart shows", lambda c: c.page.set_text("3 items in cart"))  # mutate the page
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from typing import Any

from nova_act import ActGetResult, ActMetadata, ActResult

from pynova_bdd import prompts


@dataclasses.dataclass
class FakeCall:
    method: str  # "start", "stop", "go_to_url", "act" or "act_get"
    argument: str | None = None
    kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class _Rule:
    pattern: re.Pattern[str]
    outcome: object  # exception, parsed response, None (schema mismatch), or callable(client)


class FakePage:
    """Just enough of a Playwright page for the plugin's guardrails."""

    def __init__(self, url: str = "about:blank", text: str = "Fake page") -> None:
        self.url = url
        self.text = text
        self.fields: dict[str, str] = {}

    def set_text(self, text: str) -> None:
        self.text = text

    def evaluate(self, script: str) -> dict[str, Any]:
        return {"url": self.url, "text": self.text, "fields": sorted(self.fields.items())}


class FakeNovaAct:
    """Records every call and returns scripted results.

    Without a matching rule, action steps report success and Then checks answer ``"true"``,
    quoting the fake page's text. A rule's outcome can be:

    * an exception instance, which is raised;
    * ``None``, a response that does not match the schema;
    * a dict, used as the parsed response;
    * a callable taking the fake client, which may change ``client.page``, call
      ``client.agent_navigate(url)``, and return a dict response (or ``None`` for the default).
    """

    def __init__(self, page_text: str = "Fake page") -> None:
        self.calls: list[FakeCall] = []
        self.started_with: list[dict[str, Any]] = []
        self.page_text = page_text
        self._rules: list[_Rule] = []

    # Scripting -----------------------------------------------------------------------------------
    def on(self, pattern: str, outcome: object) -> None:
        """When a step matches ``pattern`` (regex search), use ``outcome``. Later rules win."""
        self._rules.insert(0, _Rule(re.compile(pattern, re.IGNORECASE | re.DOTALL), outcome))

    def fail_when(self, pattern: str, verdict: str = "false", evidence: str = "scripted failure") -> None:
        self.on(pattern, {"verdict": verdict, "evidence": [evidence]})

    # Inspection ----------------------------------------------------------------------------------
    def prompts(self, method: str | None = None) -> list[str]:
        methods = ("act", "act_get") if method is None else (method,)
        return [c.argument or "" for c in self.calls if c.method in methods]

    def calls_of(self, method: str) -> list[FakeCall]:
        return [c for c in self.calls if c.method == method]

    # Client construction --------------------------------------------------------------------------
    def factory(self, **kwargs: Any) -> FakeClient:
        self.started_with.append({k: v for k, v in kwargs.items() if k != "state_guardrail"})
        return FakeClient(self, kwargs)

    def _outcome(self, prompt: str) -> tuple[bool, object]:
        # Match against the step itself, not the contract text wrapped around it.
        target = prompt.rsplit("Step: ", 1)[-1].rsplit("Statement: ", 1)[-1]
        for rule in self._rules:
            if rule.pattern.search(target):
                return True, rule.outcome
        return False, None


class FakeClient:
    def __init__(self, owner: FakeNovaAct, kwargs: dict[str, Any]) -> None:
        self._owner = owner
        self.kwargs = kwargs
        self.page = FakePage(text=owner.page_text)
        self._guardrail: Callable[[Any], Any] | None = kwargs.get("state_guardrail")
        self._act_count = 0

    def _record(self, method: str, argument: str | None = None, **kwargs: Any) -> None:
        self._owner.calls.append(FakeCall(method, argument, kwargs))

    def _metadata(self, prompt: str) -> ActMetadata:
        self._act_count += 1
        return ActMetadata(
            session_id="fake-session",
            act_id=f"fake-act-{self._act_count}",
            num_steps_executed=1,
            start_time=None,
            end_time=None,
            prompt=prompt,
        )

    def _check_guardrail(self, url: str) -> None:
        from nova_act import ActStateGuardrailError, GuardrailDecision, GuardrailInputState

        if self._guardrail is not None:
            decision = self._guardrail(GuardrailInputState(browser_url=url))
            if decision == GuardrailDecision.BLOCK:
                raise ActStateGuardrailError(f"Blocked by state guardrail: {url}")

    def agent_navigate(self, url: str) -> None:
        """Simulate the agent itself moving the browser (for guardrail tests)."""
        self._check_guardrail(url)
        self.page.url = url

    def start(self) -> None:
        starting_page = self.kwargs.get("starting_page")
        self._record("start", starting_page)
        if starting_page:
            self._check_guardrail(starting_page)
            self.page.url = starting_page

    def stop(self) -> None:
        self._record("stop")

    def go_to_url(self, url: str) -> None:
        self._record("go_to_url", url)
        self._check_guardrail(url)
        self.page.url = url

    def act(self, prompt: str, **kwargs: Any) -> ActResult:
        self._record("act", prompt, **kwargs)
        matched, outcome = self._owner._outcome(prompt)
        if matched and isinstance(outcome, BaseException):
            raise outcome
        if matched and callable(outcome):
            outcome(self)
        return ActResult(metadata=self._metadata(prompt))

    def _default_response(self, schema: Any) -> dict[str, Any]:
        if schema == prompts.ACTION_SCHEMA:
            return {"completed_as_written": True, "deviation": ""}
        return {"verdict": "true", "evidence": [self.page.text]}

    def act_get(self, prompt: str, schema: Any = None, **kwargs: Any) -> ActGetResult:
        self._record("act_get", prompt, schema=schema, **kwargs)
        matched, outcome = self._owner._outcome(prompt)
        parsed: object
        if not matched:
            parsed = self._default_response(schema)
        elif isinstance(outcome, BaseException):
            raise outcome
        elif callable(outcome):
            returned = outcome(self)
            parsed = self._default_response(schema) if returned is None else returned
        else:
            parsed = outcome
        return ActGetResult(
            metadata=self._metadata(prompt),
            response=None if parsed is None else str(parsed),
            parsed_response=parsed,  # type: ignore[arg-type]
            valid_json=parsed is not None,
            matches_schema=parsed is not None,
        )
