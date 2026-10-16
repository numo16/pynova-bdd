"""Choose between API-key and IAM authentication (docs/DESIGN.md §4.9)."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Literal

from pynova_bdd.config import NovaConfig
from pynova_bdd.errors import NovaConfigError

if TYPE_CHECKING:
    from nova_act import Workflow

API_KEY_ENV = "NOVA_ACT_API_KEY"


@dataclasses.dataclass(frozen=True)
class ResolvedAuth:
    mode: Literal["api_key", "iam"]
    api_key: str | None = None


def _has_aws_credentials() -> bool:
    import boto3

    return boto3.Session().get_credentials() is not None


def resolve_auth(
    config: NovaConfig,
    env: Mapping[str, str] | None = None,
    has_aws_credentials: Callable[[], bool] = _has_aws_credentials,
) -> ResolvedAuth:
    env = os.environ if env is None else env
    api_key = env.get(API_KEY_ENV) or None

    mode = config.auth
    if mode == "auto":
        if api_key:
            mode = "api_key"
        elif has_aws_credentials():
            mode = "iam"
        else:
            raise NovaConfigError(
                "No Nova Act credentials found. Set NOVA_ACT_API_KEY, or configure AWS credentials "
                "(profile, environment or role) and nova_workflow_definition for IAM auth."
            )

    if mode == "api_key":
        if not api_key:
            raise NovaConfigError("nova_auth is 'api_key' but NOVA_ACT_API_KEY is not set.")
        return ResolvedAuth(mode="api_key", api_key=api_key)

    if not config.workflow_definition:
        raise NovaConfigError(
            "IAM auth needs a Nova Act workflow definition: set nova_workflow_definition in your pytest ini."
        )
    return ResolvedAuth(mode="iam")


def build_workflow(config: NovaConfig) -> Workflow:
    """Create (but do not enter) the Nova Act Workflow used for IAM auth."""
    from nova_act import Workflow

    boto_kwargs: dict[str, str] = {}
    if config.aws_profile:
        boto_kwargs["profile_name"] = config.aws_profile
    if config.aws_region:
        boto_kwargs["region_name"] = config.aws_region
    return Workflow(
        model_id=config.model_id,
        workflow_definition_name=config.workflow_definition,
        boto_session_kwargs=boto_kwargs or None,  # type: ignore[arg-type]
    )
