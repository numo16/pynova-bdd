"""Guardrails that keep Nova steps honest (docs/DESIGN.md §4.10).

Everything here is enforced by the plugin, independent of what the model says it did.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# --- Layer 1: deterministic sampling ----------------------------------------------------------------


def derive_seed(test_id: str, step_text: str) -> int:
    """A stable seed per test and step, so reruns of the same build sample the same way."""
    digest = hashlib.sha256(f"{test_id}\x00{step_text}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


# --- Layer 2: navigation fence ----------------------------------------------------------------------

_ALWAYS_ALLOWED_SCHEMES = {"about", "blob"}


def origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc.lower()}"


def _without_fragment(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(fragment=""))


class NavigationFence:
    """A Nova Act ``state_guardrail`` that blocks URLs outside the allowed origins.

    While ``locked`` (during a Then check), any URL other than the locked one is blocked too.
    """

    def __init__(self, origins: Iterable[str] = ()) -> None:
        self.origins: set[str] = set(origins)
        self.locked_url: str | None = None
        self.blocked: list[str] = []

    def allow(self, url: str) -> None:
        origin = origin_of(url)
        if origin is not None:
            self.origins.add(origin)

    def permits(self, url: str) -> bool:
        scheme = urlsplit(url).scheme
        if scheme in _ALWAYS_ALLOWED_SCHEMES:
            return self.locked_url is None
        if self.locked_url is not None:
            return _without_fragment(url) == _without_fragment(self.locked_url)
        return origin_of(url) in self.origins

    def __call__(self, state: Any) -> Any:
        from nova_act import GuardrailDecision

        url = str(state.browser_url)
        if self.permits(url):
            return GuardrailDecision.PASS
        self.blocked.append(url)
        return GuardrailDecision.BLOCK


# --- Layer 3: read-only verification ----------------------------------------------------------------

# Collects what a Then check must not change: URL, visible text, and form state.
FINGERPRINT_JS = """
() => ({
  url: window.location.href,
  text: document.body ? document.body.innerText : "",
  fields: Array.from(document.querySelectorAll("input, select, textarea")).map((el) =>
    [el.name || el.id || el.tagName, el.type === "checkbox" || el.type === "radio" ? el.checked : el.value]
  ),
})
"""


@dataclasses.dataclass(frozen=True)
class PageFingerprint:
    url: str
    text: str
    fields: tuple[tuple[str, str], ...]

    @classmethod
    def capture(cls, page: Any) -> PageFingerprint:
        raw = page.evaluate(FINGERPRINT_JS)
        return cls(
            url=str(raw.get("url", "")),
            text=str(raw.get("text", "")),
            fields=tuple((str(name), str(value)) for name, value in raw.get("fields", [])),
        )

    def differences(self, other: PageFingerprint) -> list[str]:
        changes = []
        if _without_fragment(self.url) != _without_fragment(other.url):
            changes.append(f"URL changed from {self.url} to {other.url}")
        if normalize(self.text) != normalize(other.text):
            changes.append("page text changed")
        if self.fields != other.fields:
            changes.append("form values changed")
        return changes


# --- Layer 4: grounded verdicts ---------------------------------------------------------------------

_WS = re.compile(r"\s+")
_QUOTED = re.compile(r'"([^"]+)"')
# A statement containing any of these is not checked literally: "does not contain "X"" is true
# precisely when X is absent.
_NEGATION = re.compile(
    r"\b(not|no|never|none|without|absent|missing|removed|hidden|disappear\w*|gone|isn't|aren't|"
    r"doesn't|don't|won't|cannot|can't|neither|nor)\b",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Whitespace-collapsed, case-folded text (innerText applies CSS text-transform)."""
    return _WS.sub(" ", text).strip().casefold()


def ungrounded_quotes(quotes: Iterable[str], page_text: str) -> list[str]:
    haystack = normalize(page_text)
    return [quote for quote in quotes if normalize(quote) not in haystack]


def literal_expectations(statement: str) -> list[str]:
    """Double-quoted strings in a positive Then statement, which must be on the page."""
    if _NEGATION.search(statement):
        return []
    return _QUOTED.findall(statement)
