from __future__ import annotations

import pytest

from pynova_bdd import guardrails


def test_origin_of() -> None:
    assert guardrails.origin_of("https://Shop.Example.com/a?b") == "https://shop.example.com"
    assert guardrails.origin_of("http://localhost:8000/") == "http://localhost:8000"
    assert guardrails.origin_of("about:blank") is None
    assert guardrails.origin_of("/relative") is None


def test_fence_allows_known_origins_only() -> None:
    fence = guardrails.NavigationFence(["https://shop.example.com"])
    assert fence.permits("https://shop.example.com/cart")
    assert fence.permits("about:blank")
    assert not fence.permits("https://shop.example.com.evil.net/")
    assert not fence.permits("http://shop.example.com/")  # scheme is part of the origin
    fence.allow("https://help.example.org/faq")
    assert fence.permits("https://help.example.org/contact")


def test_locked_fence_allows_only_the_current_url() -> None:
    fence = guardrails.NavigationFence(["https://shop.example.com"])
    fence.locked_url = "https://shop.example.com/cart"
    assert fence.permits("https://shop.example.com/cart")
    assert fence.permits("https://shop.example.com/cart#totals")
    assert not fence.permits("https://shop.example.com/checkout")
    assert not fence.permits("about:blank")


def test_fence_records_blocked_urls() -> None:
    from nova_act import GuardrailDecision, GuardrailInputState

    fence = guardrails.NavigationFence(["https://shop.example.com"])
    assert fence(GuardrailInputState(browser_url="https://shop.example.com/")) == GuardrailDecision.PASS
    assert fence(GuardrailInputState(browser_url="https://evil.net/")) == GuardrailDecision.BLOCK
    assert fence.blocked == ["https://evil.net/"]


def test_seed_is_stable_and_step_specific() -> None:
    a = guardrails.derive_seed("test_a.py::test_x", "I click login")
    assert a == guardrails.derive_seed("test_a.py::test_x", "I click login")
    assert a != guardrails.derive_seed("test_a.py::test_x", "I click logout")
    assert a != guardrails.derive_seed("test_a.py::test_y", "I click login")
    assert 0 <= a < 2**31


def test_ungrounded_quotes() -> None:
    page = "Your Cart\n\n  3 items   Total: $12.00"
    assert guardrails.ungrounded_quotes(["your cart", "3 items total: $12.00"], page) == []
    assert guardrails.ungrounded_quotes(["4 items"], page) == ["4 items"]


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ('the list contains "Buy milk"', ["Buy milk"]),
        ('"A" and "B" are shown', ["A", "B"]),
        ("the cart is empty", []),
        ('the list does not contain "Buy milk"', []),
        ('"Buy milk" is no longer shown', []),
        ('the banner "Sale" is hidden', []),
        ('there isn\'t a "Sale" banner', []),
    ],
)
def test_literal_expectations(statement: str, expected: list[str]) -> None:
    assert guardrails.literal_expectations(statement) == expected


def test_fingerprint_differences() -> None:
    a = guardrails.PageFingerprint("https://x.com/a", "Hello  world", (("q", "1"),))
    assert (
        a.differences(guardrails.PageFingerprint("https://x.com/a#top", "hello world", (("q", "1"),))) == []
    )
    b = guardrails.PageFingerprint("https://x.com/b", "Hello world!", (("q", "2"),))
    assert a.differences(b) == [
        "URL changed from https://x.com/a to https://x.com/b",
        "page text changed",
        "form values changed",
    ]
