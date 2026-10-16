from __future__ import annotations

import pytest

from pynova_bdd import prompts


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ('I am on "https://example.com"', "https://example.com"),
        ("I am on https://example.com/a?b=c", "https://example.com/a?b=c"),
        ("I navigate to '/cart'", "/cart"),
        ("I go to /cart", "/cart"),
        ('I open the page "https://example.com"', "https://example.com"),
        ("i visit http://localhost:8000/", "http://localhost:8000/"),
    ],
)
def test_navigation_target(text: str, url: str) -> None:
    assert prompts.navigation_target(text) == url


@pytest.mark.parametrize(
    "text",
    [
        "I am on the home page",
        'I go to "https://example.com" and click login',
        "I search for https://example.com",
        "I open the menu",
    ],
)
def test_not_navigation(text: str) -> None:
    assert prompts.navigation_target(text) is None


def test_resolve_url() -> None:
    assert prompts.resolve_url("/cart", "https://e.com/app") == "https://e.com/app/cart"
    assert prompts.resolve_url("/cart", "https://e.com/app/") == "https://e.com/app/cart"
    assert prompts.resolve_url("https://x.com", None) == "https://x.com"
    with pytest.raises(ValueError, match="nova_base_url"):
        prompts.resolve_url("/cart", None)


def test_step_body_plain() -> None:
    assert prompts.step_body("  click login  ") == "click login"


def test_empty_docstring_is_kept() -> None:
    assert prompts.step_body("write", docstring="") == 'write\n\nUse the following text:\n"""\n\n"""'


def test_action_prompt_wraps_step_in_contract() -> None:
    text = prompts.action_prompt("click login")
    assert text.endswith("Step: click login")
    assert "Do not look for another way" in text
    assert "completed_as_written=false" in text


def test_verify_prompt_is_observe_only() -> None:
    text = prompts.verify_prompt("the cart is empty")
    assert text.endswith("Statement: the cart is empty")
    assert "Do not click, type" in text
    assert 'verdict="unsure"' in text
