from __future__ import annotations

import pytest

from pynova_bdd.config import NovaConfig

CAPTURE = """
import json
def test_cfg(nova_config):
    import dataclasses
    with open("cfg.json", "w") as fh:
        json.dump(dataclasses.asdict(nova_config), fh)
"""


def _cfg(pytester: pytest.Pytester, *args: str) -> dict[str, object]:
    import json

    pytester.makepyfile(test_cfg=CAPTURE)
    pytester.runpytest(*args).assert_outcomes(passed=1)
    result: dict[str, object] = json.loads((pytester.path / "cfg.json").read_text())
    return result


def test_defaults(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    import dataclasses

    assert _cfg(pytester) == dataclasses.asdict(NovaConfig())


def test_ci_env_makes_headless_default(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert _cfg(pytester)["headless"] is True


def test_ini_and_cli(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    pytester.makeini(
        """
        [pytest]
        nova_base_url = https://ini.example.com
        nova_auth = iam
        nova_workflow_definition = suite
        nova_aws_region = eu-west-1
        nova_then_mode = ACT
        """
    )
    cfg = _cfg(pytester, "--nova-base-url", "https://cli.example.com", "--nova-auth", "api_key")
    assert cfg["base_url"] == "https://cli.example.com"
    assert cfg["auth"] == "api_key"
    assert cfg["workflow_definition"] == "suite"
    assert cfg["aws_region"] == "eu-west-1"
    assert cfg["then_mode"] == "act"
