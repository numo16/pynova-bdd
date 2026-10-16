from __future__ import annotations

import pytest

from pynova_bdd.auth import build_workflow, resolve_auth
from pynova_bdd.config import NovaConfig
from pynova_bdd.errors import NovaConfigError


def creds(value: bool):  # type: ignore[no-untyped-def]
    return lambda: value


def test_auto_prefers_api_key() -> None:
    auth = resolve_auth(NovaConfig(), env={"NOVA_ACT_API_KEY": "k"}, has_aws_credentials=creds(True))
    assert auth.mode == "api_key"
    assert auth.api_key == "k"


def test_auto_falls_back_to_iam() -> None:
    auth = resolve_auth(NovaConfig(workflow_definition="suite"), env={}, has_aws_credentials=creds(True))
    assert auth.mode == "iam"


def test_auto_without_anything_fails_clearly() -> None:
    with pytest.raises(NovaConfigError, match="No Nova Act credentials found"):
        resolve_auth(NovaConfig(), env={}, has_aws_credentials=creds(False))


def test_iam_needs_workflow_definition() -> None:
    with pytest.raises(NovaConfigError, match="nova_workflow_definition"):
        resolve_auth(NovaConfig(), env={}, has_aws_credentials=creds(True))


def test_forced_api_key_without_key_fails() -> None:
    with pytest.raises(NovaConfigError, match="NOVA_ACT_API_KEY is not set"):
        resolve_auth(NovaConfig(auth="api_key"), env={}, has_aws_credentials=creds(True))


def test_forced_iam_ignores_api_key() -> None:
    auth = resolve_auth(
        NovaConfig(auth="iam", workflow_definition="suite"),
        env={"NOVA_ACT_API_KEY": "k"},
        has_aws_credentials=creds(False),
    )
    assert auth.mode == "iam"
    assert auth.api_key is None


def test_build_workflow_passes_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class RecordingWorkflow:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("nova_act.Workflow", RecordingWorkflow)
    build_workflow(
        NovaConfig(model_id="m", workflow_definition="suite", aws_profile="qa", aws_region="eu-west-1")
    )
    assert captured == {
        "model_id": "m",
        "workflow_definition_name": "suite",
        "boto_session_kwargs": {"profile_name": "qa", "region_name": "eu-west-1"},
    }
