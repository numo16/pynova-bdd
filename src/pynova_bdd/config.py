"""Plugin configuration: ini options and command-line flags resolved into one object."""

from __future__ import annotations

import dataclasses
import os
from typing import Literal

import pytest

AuthMode = Literal["auto", "api_key", "iam"]
ThenMode = Literal["verify", "act"]

_AUTH_MODES: tuple[AuthMode, ...] = ("auto", "api_key", "iam")
_THEN_MODES: tuple[ThenMode, ...] = ("verify", "act")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


@dataclasses.dataclass(frozen=True)
class NovaConfig:
    enabled: bool = True
    base_url: str | None = None
    headless: bool = False
    max_steps: int | None = None
    timeout: int | None = None
    then_mode: ThenMode = "verify"
    auth: AuthMode = "auto"
    model_id: str = "nova-act-latest"
    workflow_definition: str | None = None
    aws_profile: str | None = None
    aws_region: str | None = None


# (ini name, help, default) — defaults are strings because pytest ini values are.
_INI_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("nova_enabled", "Route steps without a Python definition to Nova Act.", "true"),
    ("nova_base_url", "Base URL; relative URLs in navigation steps resolve against it.", ""),
    ("nova_headless", "Run the browser headless. Defaults to true when the CI env var is set.", ""),
    ("nova_max_steps", "Maximum browser actions per Nova step (Nova Act default when empty).", ""),
    ("nova_timeout", "Timeout in seconds per Nova step (Nova Act default when empty).", ""),
    ("nova_then_mode", "How Then steps run: 'verify' (yes/no check) or 'act'.", "verify"),
    ("nova_auth", "Authentication: 'auto', 'api_key' or 'iam'.", "auto"),
    ("nova_model_id", "Nova Act model id used with IAM auth.", "nova-act-latest"),
    ("nova_workflow_definition", "Nova Act workflow definition name (required for IAM auth).", ""),
    ("nova_aws_profile", "AWS profile for IAM auth (boto default chain when empty).", ""),
    ("nova_aws_region", "AWS region for IAM auth.", ""),
)


def add_options(parser: pytest.Parser) -> None:
    for name, help_text, default in _INI_OPTIONS:
        parser.addini(name, help_text, default=default)

    group = parser.getgroup("nova-bdd", "Nova Act for pytest-bdd")
    group.addoption(
        "--nova",
        dest="nova_enabled",
        action="store_const",
        const=True,
        default=None,
        help="Route steps without a Python definition to Nova Act (default).",
    )
    group.addoption(
        "--no-nova",
        dest="nova_enabled",
        action="store_const",
        const=False,
        help="Never use Nova Act; unmatched steps fail as in plain pytest-bdd.",
    )
    group.addoption("--nova-base-url", dest="nova_base_url", default=None, help="Override nova_base_url.")
    group.addoption(
        "--nova-headless",
        dest="nova_headless",
        action="store_const",
        const=True,
        default=None,
        help="Run the browser headless.",
    )
    group.addoption(
        "--nova-headed",
        dest="nova_headless",
        action="store_const",
        const=False,
        help="Run the browser with a visible window.",
    )
    group.addoption(
        "--nova-auth", dest="nova_auth", choices=_AUTH_MODES, default=None, help="Override nova_auth."
    )


def _parse_bool(name: str, value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise pytest.UsageError(f"{name} must be true or false, got {value!r}")


def _parse_int(name: str, value: str) -> int | None:
    if not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise pytest.UsageError(f"{name} must be an integer, got {value!r}") from None
    if parsed <= 0:
        raise pytest.UsageError(f"{name} must be positive, got {parsed}")
    return parsed


def _parse_choice(name: str, value: str, choices: tuple[str, ...]) -> str:
    lowered = value.strip().lower()
    if lowered not in choices:
        raise pytest.UsageError(f"{name} must be one of {', '.join(choices)}; got {value!r}")
    return lowered


def _ini(config: pytest.Config, name: str) -> str:
    value = config.getini(name)
    return str(value).strip() if value is not None else ""


def load_config(config: pytest.Config) -> NovaConfig:
    """Resolve settings with precedence ini < command line."""

    def opt(name: str) -> object:
        return config.getoption(name, default=None)

    cli_enabled = opt("nova_enabled")
    enabled = (
        cli_enabled
        if isinstance(cli_enabled, bool)
        else _parse_bool("nova_enabled", _ini(config, "nova_enabled"))
    )

    cli_headless = opt("nova_headless")
    if isinstance(cli_headless, bool):
        headless = cli_headless
    elif _ini(config, "nova_headless"):
        headless = _parse_bool("nova_headless", _ini(config, "nova_headless"))
    else:
        headless = bool(os.environ.get("CI"))

    base_url = opt("nova_base_url") or _ini(config, "nova_base_url") or None
    auth = opt("nova_auth") or _parse_choice("nova_auth", _ini(config, "nova_auth"), _AUTH_MODES)

    return NovaConfig(
        enabled=enabled,
        base_url=str(base_url) if base_url else None,
        headless=headless,
        max_steps=_parse_int("nova_max_steps", _ini(config, "nova_max_steps")),
        timeout=_parse_int("nova_timeout", _ini(config, "nova_timeout")),
        then_mode=_parse_choice("nova_then_mode", _ini(config, "nova_then_mode"), _THEN_MODES),  # type: ignore[arg-type]
        auth=auth,  # type: ignore[arg-type]
        model_id=_ini(config, "nova_model_id") or "nova-act-latest",
        workflow_definition=_ini(config, "nova_workflow_definition") or None,
        aws_profile=_ini(config, "nova_aws_profile") or None,
        aws_region=_ini(config, "nova_aws_region") or None,
    )
