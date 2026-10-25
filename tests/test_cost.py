"""Tests for the zero-cost pricing-gap check (design §9.2)."""

from __future__ import annotations

from aidw.cost import is_unpriced, provider_of, total_tokens

UNPRICED = {
    "input_tokens": 42726,
    "output_tokens": 19242,
    "cache_read": 873984,
    "cache_write": 0,
    "reasoning": 12188,
    "total_tokens": 935952,
    "cost_usd": 0.0,
}


def test_provider_of_takes_the_first_segment() -> None:
    assert provider_of("openrouter/deepseek/deepseek-v4.1-flash") == "openrouter"
    assert provider_of("ollama") == "ollama"
    assert provider_of("OpenRouter/x") == "openrouter"
    assert provider_of("") == ""


def test_total_tokens_prefers_pis_own_total() -> None:
    assert total_tokens(UNPRICED) == 935952


def test_total_tokens_sums_counters_without_a_total() -> None:
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read": 100, "cache_write": 1}
    assert total_tokens(usage) == 116


def test_total_tokens_is_zero_without_usage() -> None:
    assert total_tokens(None) == 0
    assert total_tokens({}) == 0


def test_unpriced_when_tokens_have_no_cost() -> None:
    assert is_unpriced("openrouter/deepseek/deepseek-v4.1-flash", UNPRICED) is True


def test_priced_usage_is_not_flagged() -> None:
    usage = dict(UNPRICED, cost_usd=0.0286)
    assert is_unpriced("openrouter/deepseek/deepseek-v4.1-flash", usage) is False


def test_local_provider_is_not_flagged() -> None:
    assert is_unpriced("ollama/qwen3.8:27b-mlx", UNPRICED) is False


def test_usage_without_tokens_is_not_flagged() -> None:
    assert is_unpriced("openrouter/deepseek/deepseek-v4.1-flash", {"cost_usd": 0.0}) is False
    assert is_unpriced("openrouter/deepseek/deepseek-v4.1-flash", None) is False
    assert is_unpriced("openrouter/deepseek/deepseek-v4.1-flash", {}) is False
