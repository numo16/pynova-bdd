"""How Nova steps behave: Then verdicts, errors, prompts and settings."""

from __future__ import annotations

from tests.conftest import NovaProject

THEN_FEATURE = """
Feature: Cart
  Scenario: Check the cart
    Given I am on "https://shop.example.com"
    Then the cart shows 3 items
"""


def test_then_false_fails_with_evidence(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra="""
        _FAKE.fail_when("cart shows 3 items", evidence="the cart badge says 1")
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*NovaAssertionFailed: the cart shows 3 items*", "*found this to be false: the cart badge says 1*"]
    )


def test_then_without_a_verdict_is_an_error_not_a_pass(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, conftest_extra='_FAKE.on("cart shows", None)\n')
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaVerificationError: Nova Act did not return a yes/no verdict*"])


def test_then_with_non_boolean_verdict_is_an_error(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE, conftest_extra='_FAKE.on("cart shows", {"passed": "yes", "evidence": ""})\n'
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaVerificationError: Nova Act returned an invalid verdict*"])


def test_act_error_becomes_readable_failure(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Fail
          Scenario: Stuck
            Given I am on "https://shop.example.com"
            When I click the missing button
        """,
        conftest_extra="""
        from nova_act import ActExceededMaxStepsError
        _FAKE.on("missing button", ActExceededMaxStepsError("gave up"))
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*NovaStepFailed: Nova Act could not complete step: I click the missing button*",
            "*ActExceededMaxStepsError: gave up*",
        ]
    )
    result.stdout.no_fnmatch_line("*qualtrics*")
    # The browser is still closed.
    assert project.methods()[-1] == ("stop", None)


def test_missing_starting_page_is_a_config_error(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: No page
          Scenario: Nowhere
            When I click the button
        """
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaConfigError: Nova Act needs a starting page*"])


def test_base_url_is_starting_page(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Base
          Scenario: Start at base
            When I click the button
        """,
        ini="nova_base_url = https://base.example.com\n",
    )
    project.run().assert_outcomes(passed=1)
    assert project.methods()[0] == ("start", "https://base.example.com")


def test_relative_url_without_base_url_fails(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Rel
          Scenario: Relative
            Given I am on "/cart"
        """
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaConfigError: Relative URL '/cart' needs nova_base_url*"])


def test_docstring_and_datatable_are_appended(project: NovaProject) -> None:
    project.setup(
        feature='''
        Feature: Forms
          Scenario: Fill in
            Given I am on "https://shop.example.com"
            When I fill in the address form with
              | field  | value     |
              | street | 1 Main St |
            And I write a review saying
              """
              Great book.
              """
        ''',
    )
    project.run().assert_outcomes(passed=1)
    prompts = [arg for method, arg in project.methods() if method == "act"]
    assert prompts[0] == (
        "I fill in the address form with\n\n"
        "Use this data:\n| field | value |\n|---|---|\n| street | 1 Main St |"
    )
    assert prompts[1] == 'I write a review saying\n\nUse the following text:\n"""\nGreat book.\n"""'


def test_scenario_outline_values_are_substituted(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Outline
          Scenario Outline: Search
            Given I am on "https://shop.example.com"
            When I search for "<term>"

            Examples:
              | term  |
              | Dune  |
              | Emma  |
        """
    )
    project.run().assert_outcomes(passed=2)
    prompts = [arg for method, arg in project.methods() if method == "act"]
    assert prompts == ['I search for "Dune"', 'I search for "Emma"']
    # Each example gets its own browser.
    assert [m for m, _ in project.methods()].count("start") == 2


def test_settings_reach_nova_act(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Settings
          Scenario: Limits
            Given I am on "https://shop.example.com"
            When I click the button
            Then it worked
        """,
        ini="nova_max_steps = 12\nnova_timeout = 60\nnova_headless = true\n",
    )
    project.run().assert_outcomes(passed=1)
    calls = project.calls()
    assert calls["started_with"] == [{"starting_page": "https://shop.example.com", "headless": True}]
    for call in calls["calls"]:
        if call["method"] in ("act", "act_get"):
            assert call["kwargs"] == {"max_steps": 12, "timeout": 60}


def test_headed_flag_overrides_ini(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, ini="nova_headless = true\n")
    project.run("--nova-headed").assert_outcomes(passed=1)
    assert project.calls()["started_with"][0]["headless"] is False


def test_then_mode_act(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, ini="nova_then_mode = act\n")
    project.run().assert_outcomes(passed=1)
    assert ("act", "the cart shows 3 items") in project.methods()


def test_bad_ini_value_is_a_usage_error(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, ini="nova_max_steps = lots\n")
    result = project.run()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*nova_max_steps must be an integer*"])
