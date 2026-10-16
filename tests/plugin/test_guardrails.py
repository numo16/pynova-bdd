"""A misbehaving agent must not turn a step green (docs/DESIGN.md §4.10, threats T1-T5).

Each test scripts FakeNovaAct to "cheat" in one way and checks that the plugin fails the step.
"""

from __future__ import annotations

from tests.conftest import NovaProject

ACTION_FEATURE = """
Feature: Shop
  Scenario: Add to cart
    Given I am on "https://shop.example.com"
    When I click "Add to cart"
"""

THEN_FEATURE = """
Feature: Shop
  Scenario: Check the cart
    Given I am on "https://shop.example.com"
    Then the cart shows 3 items
"""


# --- T1: workarounds -------------------------------------------------------------------------------


def test_reported_deviation_fails_the_step(project: NovaProject) -> None:
    project.setup(
        feature=ACTION_FEATURE,
        conftest_extra="""
        _FAKE.on("Add to cart", {
            "completed_as_written": False,
            "deviation": "No Add to cart button; used Buy now on the product page instead",
        })
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*NovaStepFailed: Nova Act could not do the step exactly as written: I click*",
            "*deviation: No Add to cart button; used Buy now*",
        ]
    )


def test_deviation_with_completed_true_still_fails(project: NovaProject) -> None:
    project.setup(
        feature=ACTION_FEATURE,
        conftest_extra="""
        _FAKE.on("Add to cart", {"completed_as_written": True, "deviation": "closed a promo popup first"})
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*deviation: closed a promo popup first*"])


def test_action_without_a_report_fails(project: NovaProject) -> None:
    project.setup(feature=ACTION_FEATURE, conftest_extra='_FAKE.on("Add to cart", None)\n')
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaStepFailed: Nova Act did not report whether it completed the step*"])


def test_actions_run_under_the_step_contract_with_a_tight_budget(project: NovaProject) -> None:
    project.setup(feature=ACTION_FEATURE)
    project.run().assert_outcomes(passed=1)
    call = next(c for c in project.calls()["calls"] if c["method"] == "act_get")
    assert "Do not look for another way" in call["argument"]
    assert call["kwargs"]["max_steps"] == 10
    assert call["kwargs"]["model_temperature"] == 0.0


# --- T2: leaving the app ---------------------------------------------------------------------------


def test_agent_navigating_off_site_is_blocked(project: NovaProject) -> None:
    project.setup(
        feature=ACTION_FEATURE,
        conftest_extra="""
        _FAKE.on("Add to cart", lambda c: c.agent_navigate("https://coupons.example.net/deal"))
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*NovaStepFailed: Nova Act could not complete step: I click*",
            "*ActStateGuardrailError*",
            "*Navigation was blocked by the guardrail: https://coupons.example.net/deal*",
        ]
    )


def test_navigation_within_the_app_is_allowed(project: NovaProject) -> None:
    project.setup(
        feature=ACTION_FEATURE,
        conftest_extra="""
        _FAKE.on("Add to cart", lambda c: c.agent_navigate("https://shop.example.com/cart"))
        """,
    )
    project.run().assert_outcomes(passed=1)


def test_allowed_origins_extend_the_fence(project: NovaProject) -> None:
    project.setup(
        feature=ACTION_FEATURE,
        conftest_extra="""
        _FAKE.on("Add to cart", lambda c: c.agent_navigate("https://login.example.org/authorize"))
        """,
        ini="nova_allowed_origins =\n    https://login.example.org\n",
    )
    project.run().assert_outcomes(passed=1)


def test_explicit_navigation_steps_extend_the_fence(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Two apps
          Scenario: Hop
            Given I am on "https://shop.example.com"
            When I go to https://help.example.org/faq
            And I click "Contact"
        """,
        conftest_extra="""
        _FAKE.on("Contact", lambda c: c.agent_navigate("https://help.example.org/contact"))
        """,
    )
    project.run().assert_outcomes(passed=1)


def test_then_check_may_not_navigate_even_within_the_app(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra="""
        _FAKE.on("cart shows", lambda c: c.agent_navigate("https://shop.example.com/cart"))
        """,
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*Navigation was blocked by the guardrail: https://shop.example.com/cart*"])


# --- T4: verification that changes the page --------------------------------------------------------


def _mutating_check(change: str) -> str:
    return f"""
def _cheat(c):
    {change}
    return {{"verdict": "true", "evidence": ["Fake page"]}}
_FAKE.on("cart shows", _cheat)
"""


def test_then_check_that_changes_page_text_fails(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra=_mutating_check('c.page.set_text("Fake page. Cart: 3 items")'),
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*NovaVerificationError: The check modified the page, so its verdict is not trusted*", "*page text*"]
    )


def test_then_check_that_changes_a_form_field_fails(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, conftest_extra=_mutating_check('c.page.fields["qty"] = "3"'))
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*The check modified the page*", "*form values changed*"])


def test_readonly_check_can_be_disabled(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra=_mutating_check('c.page.set_text("Fake page. Cart: 3 items")'),
        ini="nova_readonly_check = false\n",
    )
    project.run().assert_outcomes(passed=1)


def test_then_check_has_a_small_budget(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE)
    project.run().assert_outcomes(passed=1)
    call = next(c for c in project.calls()["calls"] if c["method"] == "act_get")
    assert call["kwargs"]["max_steps"] == 3


# --- T5: hallucinated or lenient verdicts ----------------------------------------------------------


def test_unsure_verdict_fails(project: NovaProject) -> None:
    project.setup(feature=THEN_FEATURE, conftest_extra='_FAKE.fail_when("cart shows", verdict="unsure")\n')
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*NovaAssertionFailed: the cart shows 3 items*", "*could not confirm this (unsure)*"]
    )


def test_true_without_evidence_fails(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE, conftest_extra='_FAKE.on("cart shows", {"verdict": "true", "evidence": []})\n'
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*NovaVerificationError: Nova Act said true but quoted no page text*"])


def test_invented_evidence_fails(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra='_FAKE.on("cart shows", {"verdict": "true", "evidence": ["Cart (3 items)"]})\n',
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*NovaVerificationError: Nova Act's evidence is not on the page*", "*not found:*Cart (3 items)*"]
    )


def test_evidence_matches_despite_case_and_whitespace(project: NovaProject) -> None:
    project.setup(
        feature=THEN_FEATURE,
        conftest_extra="""
        _FAKE.page_text = "YOUR CART\\n  3   items"
        _FAKE.on("cart shows", {"verdict": "true", "evidence": ["Your cart 3 items"]})
        """,
    )
    project.run().assert_outcomes(passed=1)


LIST_FEATURE = """
Feature: Todo
  Scenario: Check
    Given I am on "https://todo.example.com"
    Then {statement}
"""


def test_quoted_text_in_then_step_must_be_on_the_page(project: NovaProject) -> None:
    project.setup(
        feature=LIST_FEATURE.format(statement='the list contains "Buy milk"'),
        conftest_extra='_FAKE.page_text = "Todo: Walk the dog"\n',
    )
    result = project.run()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*NovaAssertionFailed: the list contains*", "*Quoted text not found on the page:*Buy milk*"]
    )


def test_quoted_text_present_passes(project: NovaProject) -> None:
    project.setup(
        feature=LIST_FEATURE.format(statement='the list contains "Buy milk"'),
        conftest_extra='_FAKE.page_text = "Todo: Buy milk"\n',
    )
    project.run().assert_outcomes(passed=1)


def test_negative_statements_skip_the_literal_check(project: NovaProject) -> None:
    project.setup(
        feature=LIST_FEATURE.format(statement='the list does not contain "Buy milk"'),
        conftest_extra='_FAKE.page_text = "Todo: Walk the dog"\n',
    )
    project.run().assert_outcomes(passed=1)


def test_literal_check_can_be_disabled(project: NovaProject) -> None:
    project.setup(
        feature=LIST_FEATURE.format(statement='the list contains "Buy milk"'),
        conftest_extra='_FAKE.page_text = "Todo: Walk the dog"\n',
        ini="nova_literal_check = false\n",
    )
    project.run().assert_outcomes(passed=1)


# --- T6: run-to-run determinism --------------------------------------------------------------------


def test_seeds_are_stable_across_runs(project: NovaProject) -> None:
    project.setup(feature=ACTION_FEATURE + "    Then the cart shows 1 item\n")
    project.run().assert_outcomes(passed=1)
    first = [c["kwargs"]["model_seed"] for c in project.calls()["calls"] if c["method"] == "act_get"]
    project.run().assert_outcomes(passed=1)
    second = [c["kwargs"]["model_seed"] for c in project.calls()["calls"] if c["method"] == "act_get"]
    assert first == second
    assert len(set(first)) == 2


def test_seed_and_temperature_can_be_overridden(project: NovaProject) -> None:
    project.setup(feature=ACTION_FEATURE, ini="nova_model_seed = 7\nnova_model_temperature = none\n")
    project.run().assert_outcomes(passed=1)
    call = next(c for c in project.calls()["calls"] if c["method"] == "act_get")
    assert call["kwargs"]["model_seed"] == 7
    assert "model_temperature" not in call["kwargs"]
