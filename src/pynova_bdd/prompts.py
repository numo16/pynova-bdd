"""Turn Gherkin steps into Nova Act prompts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urljoin

# "Given I am on "https://example.com"", "When I navigate to /cart", "Given I open the page "/login"" …
_NAVIGATION = re.compile(
    r"""^\s*I\s+(?:am\s+on|navigate\s+to|go\s+to|open|visit)(?:\s+the)?(?:\s+page)?\s+
        (?P<quote>["']?)(?P<url>(?:https?://|/)\S*?)(?P=quote)\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Given/When steps report whether they did exactly what was written (docs/DESIGN.md §4.10, layer 1).
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "completed_as_written": {"type": "boolean"},
        "deviation": {"type": "string"},
    },
    "required": ["completed_as_written", "deviation"],
}

# Then steps answer true/false/unsure and quote the page text they relied on (layer 4).
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["true", "false", "unsure"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "evidence"],
}

_ACTION_CONTRACT = (
    "You are executing one step of an automated acceptance test. Rules:\n"
    "1. Do exactly what the step says, using only the controls visible in the app. Nothing more.\n"
    "2. Do not type URLs, edit the address bar, reload, go back, or open new tabs or windows.\n"
    "3. Do not dismiss, work around, or fix anything the step does not mention.\n"
    "4. If the step cannot be done exactly as written (a control is missing, disabled, or different), "
    "stop immediately. Do not look for another way. Report completed_as_written=false and describe "
    "what was different in deviation.\n"
    '5. When done, report completed_as_written=true and deviation="".'
)


def navigation_target(step_text: str) -> str | None:
    """Return the URL if the step is a plain navigation, so it can skip the model."""
    match = _NAVIGATION.match(step_text)
    return match.group("url") if match else None


def resolve_url(url: str, base_url: str | None) -> str:
    if url.startswith("/"):
        if not base_url:
            raise ValueError(f"Relative URL {url!r} needs nova_base_url to be set.")
        return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
    return url


def _render_table(rows: Sequence[Sequence[object]]) -> str:
    if not rows:
        return ""
    lines = ["| " + " | ".join(str(cell) for cell in rows[0]) + " |"]
    lines.append("|" + "---|" * len(rows[0]))
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows[1:])
    return "\n".join(lines)


def step_body(
    step_text: str,
    docstring: str | None = None,
    datatable: Sequence[Sequence[object]] | None = None,
) -> str:
    parts = [step_text.strip()]
    if docstring is not None:
        parts.append(f'Use the following text:\n"""\n{docstring}\n"""')
    if datatable:
        parts.append(f"Use this data:\n{_render_table(datatable)}")
    return "\n\n".join(parts)


def action_prompt(
    step_text: str,
    docstring: str | None = None,
    datatable: Sequence[Sequence[object]] | None = None,
) -> str:
    return f"{_ACTION_CONTRACT}\n\nStep: {step_body(step_text, docstring, datatable)}"


def verify_prompt(
    step_text: str,
    docstring: str | None = None,
    datatable: Sequence[Sequence[object]] | None = None,
) -> str:
    statement = step_body(step_text, docstring, datatable)
    return (
        "You are checking one expectation of an automated acceptance test. You are an observer:\n"
        "1. Do not click, type, select, submit, navigate, or change the page in any way. "
        "You may only scroll to read.\n"
        '2. Answer verdict="true" only if the page clearly shows the statement is true, '
        'verdict="false" if it shows it is false, and verdict="unsure" otherwise.\n'
        "3. In evidence, quote the exact text visible on the page that supports your verdict.\n\n"
        f"Statement: {statement}"
    )
