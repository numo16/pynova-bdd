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
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from nova_act import ActGetResult, ActMetadata, ActResult


@dataclasses.dataclass
class FakeCall:
    method: str  # "start", "stop", "go_to_url", "act" or "act_get"
    argument: str | None = None
    kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class _Rule:
    pattern: re.Pattern[str]
    outcome: object  # exception instance, or the parsed response for act_get


class FakeNovaAct:
    """Records every call and returns scripted results.

    ``act()`` succeeds unless a rule matching the prompt holds an exception. ``act_get()`` returns
    ``{"passed": True, ...}`` unless a rule supplies another parsed response or an exception.
    A rule set to ``None`` gives a response that does not match the schema.
    """

    def __init__(self) -> None:
        self.calls: list[FakeCall] = []
        self.started_with: list[dict[str, Any]] = []
        self._rules: list[_Rule] = []

    # Scripting -----------------------------------------------------------------------------------
    def on(self, pattern: str, outcome: object) -> None:
        """When a prompt matches ``pattern`` (regex search), use ``outcome``. Later rules win."""
        self._rules.insert(0, _Rule(re.compile(pattern, re.IGNORECASE | re.DOTALL), outcome))

    def fail_when(self, pattern: str, passed: bool = False, evidence: str = "scripted failure") -> None:
        self.on(pattern, {"passed": passed, "evidence": evidence})

    # Inspection ----------------------------------------------------------------------------------
    def prompts(self, method: str | None = None) -> list[str]:
        return [
            c.argument or ""
            for c in self.calls
            if c.method in (("act", "act_get") if method is None else (method,))
        ]

    def calls_of(self, method: str) -> list[FakeCall]:
        return [c for c in self.calls if c.method == method]

    # Client construction --------------------------------------------------------------------------
    def factory(self, **kwargs: Any) -> _FakeClient:
        self.started_with.append(kwargs)
        return _FakeClient(self, kwargs)

    def _outcome(self, prompt: str) -> tuple[bool, object]:
        for rule in self._rules:
            if rule.pattern.search(prompt):
                return True, rule.outcome
        return False, None


class _FakeClient:
    def __init__(self, owner: FakeNovaAct, kwargs: dict[str, Any]) -> None:
        self._owner = owner
        self.kwargs = kwargs
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

    def start(self) -> None:
        self._record("start", self.kwargs.get("starting_page"))

    def stop(self) -> None:
        self._record("stop")

    def go_to_url(self, url: str) -> None:
        self._record("go_to_url", url)

    def act(self, prompt: str, **kwargs: Any) -> ActResult:
        self._record("act", prompt, **kwargs)
        matched, outcome = self._owner._outcome(prompt)
        if matched and isinstance(outcome, BaseException):
            raise outcome
        return ActResult(metadata=self._metadata(prompt))

    def act_get(self, prompt: str, schema: Any = None, **kwargs: Any) -> ActGetResult:
        self._record("act_get", prompt, schema=schema, **kwargs)
        matched, outcome = self._owner._outcome(prompt)
        if matched and isinstance(outcome, BaseException):
            raise outcome
        parsed = outcome if matched else {"passed": True, "evidence": "fake"}
        return ActGetResult(
            metadata=self._metadata(prompt),
            response=None if parsed is None else str(parsed),
            parsed_response=parsed,  # type: ignore[arg-type]
            valid_json=parsed is not None,
            matches_schema=parsed is not None,
        )
