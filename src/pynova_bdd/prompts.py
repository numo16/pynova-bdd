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

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "evidence": {"type": "string"},
    },
    "required": ["passed", "evidence"],
}


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


def action_prompt(
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


def verify_prompt(
    step_text: str,
    docstring: str | None = None,
    datatable: Sequence[Sequence[object]] | None = None,
) -> str:
    statement = action_prompt(step_text, docstring, datatable)
    return (
        "Look at the current state of the browser and decide whether the following statement is true. "
        "Do not change the page unless you must scroll to check it. "
        "Answer with passed=true or passed=false, and give short evidence for your answer.\n\n"
        f"Statement: {statement}"
    )
