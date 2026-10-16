"""Which steps go to Nova Act, and which run as Python (docs/DESIGN.md §4.2)."""

from __future__ import annotations

import textwrap

from tests.conftest import NovaProject

FEATURE = """
Feature: Shop
  Scenario: Buy a book
    Given I am on "https://shop.example.com"
    When I search for "Dune"
    And I add the first result to the cart
    Then the cart shows 1 item
    And the total is shown
"""


def test_unmatched_steps_go_to_nova(project: NovaProject) -> None:
    project.setup(feature=FEATURE)
    project.run().assert_outcomes(passed=1)

    assert project.steps() == [
        ("start", "https://shop.example.com"),
        ("act", 'I search for "Dune"'),
        ("act", "I add the first result to the cart"),
        ("verify", "the cart shows 1 item"),
        ("verify", "the total is shown"),
        ("stop", None),
    ]


def test_navigation_step_skips_the_model(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Nav
          Scenario: Two pages
            Given I am on "https://a.example.com"
            When I navigate to https://b.example.com/x
            And I go to /relative
        """,
        ini="nova_base_url = https://base.example.com/app\n",
    )
    project.run().assert_outcomes(passed=1)
    assert project.methods() == [
        ("start", "https://a.example.com"),
        ("go_to_url", "https://b.example.com/x"),
        ("go_to_url", "https://base.example.com/app/relative"),
        ("stop", None),
    ]


def test_module_step_definition_wins(project: NovaProject) -> None:
    project.setup(
        feature=FEATURE,
        test="""
        from pytest_bdd import scenarios, when, then, parsers
        scenarios("example.feature")

        @when(parsers.parse('I search for "{term}"'))
        def search(term):
            assert term == "Dune"

        @then("the cart shows 1 item")
        def cart():
            pass
        """,
    )
    project.run().assert_outcomes(passed=1)
    prompts = [arg for _, arg in project.steps()]
    assert not any("Dune" in (p or "") for p in prompts)
    assert not any("cart shows" in (p or "") for p in prompts)
    assert any("I add the first result" in (p or "") for p in prompts)


def test_root_conftest_step_definition_wins(project: NovaProject) -> None:
    project.setup(
        feature=FEATURE,
        conftest_extra="""
        from pytest_bdd import when, parsers

        @when(parsers.parse('I search for "{term}"'))
        def search(term):
            pass
        """,
    )
    project.run().assert_outcomes(passed=1)
    assert not any('"Dune"' in (arg or "") for _, arg in project.methods())


def test_nested_conftest_step_definition_wins(project: NovaProject) -> None:
    project.setup(feature=FEATURE, test="")
    sub = project.pytester.mkpydir("sub")
    (sub / "conftest.py").write_text(
        textwrap.dedent(
            """
            from pytest_bdd import when
            @when("I add the first result to the cart")
            def add():
                pass
            """
        )
    )
    (sub / "example.feature").write_text(textwrap.dedent(FEATURE))
    (sub / "test_sub.py").write_text('from pytest_bdd import scenarios\nscenarios("example.feature")\n')
    project.run().assert_outcomes(passed=1)
    assert not any("first result" in (arg or "") for _, arg in project.methods())


def test_all_python_scenario_never_starts_a_browser(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Pure
          Scenario: Python only
            Given a thing
            Then it works
        """,
        test="""
        from pytest_bdd import scenarios, given, then
        scenarios("example.feature")

        @given("a thing")
        def thing():
            pass

        @then("it works")
        def works():
            pass
        """,
    )
    project.run().assert_outcomes(passed=1)
    assert project.methods() == []


def test_python_step_can_use_nova_fixture(project: NovaProject) -> None:
    project.setup(
        feature="""
        Feature: Hybrid
          Scenario: Mixed
            Given I am on "https://shop.example.com"
            When I do something custom
            Then the page looks right
        """,
        test="""
        from pytest_bdd import scenarios, when
        scenarios("example.feature")

        @when("I do something custom")
        def custom(nova):
            nova.act("click the custom button")
        """,
    )
    project.run().assert_outcomes(passed=1)
    assert ("act", "click the custom button") in project.methods()


def test_no_nova_flag_fails_unmatched_steps(project: NovaProject) -> None:
    project.setup(feature=FEATURE)
    result = project.run("--no-nova")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*StepDefinitionNotFoundError*Nova Act is disabled*"])
    assert project.methods() == []


def test_disabled_in_ini(project: NovaProject) -> None:
    project.setup(feature=FEATURE, ini="nova_enabled = false\n")
    project.run().assert_outcomes(failed=1)
    assert project.methods() == []
    # --nova on the command line re-enables it.
    project.run("--nova").assert_outcomes(passed=1)
