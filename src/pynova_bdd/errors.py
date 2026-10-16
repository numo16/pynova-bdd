"""Exceptions raised by the plugin, and translation of Nova Act errors into readable failures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nova_act import ActError


class NovaBddError(Exception):
    """Base class for pynova_bdd errors."""


class NovaConfigError(NovaBddError):
    """The plugin is misconfigured (no starting page, no credentials, …)."""


class NovaStepFailed(NovaBddError):
    """Nova Act could not carry out a step.

    The original Nova Act exception is kept on ``act_error`` rather than chained, because its text
    is long and would bury the step that failed.
    """

    def __init__(self, message: str, act_error: ActError | None = None) -> None:
        super().__init__(message)
        self.act_error = act_error


class NovaVerificationError(NovaStepFailed):
    """Nova Act did not return a usable verdict for a Then step."""


class NovaAssertionFailed(AssertionError):
    """A Then step was checked and found to be false."""


def describe_act_error(step_text: str, error: ActError) -> str:
    """One readable message for a failed act() call, without Nova Act's long feedback footer."""
    lines = [
        f"Nova Act could not complete step: {step_text}",
        f"  {type(error).__name__}: {error.message}",
    ]
    metadata = error.metadata
    if metadata is not None:
        lines.append(
            f"  session_id={metadata.session_id} act_id={metadata.act_id} "
            f"steps_executed={metadata.num_steps_executed}"
        )
    return "\n".join(lines)
