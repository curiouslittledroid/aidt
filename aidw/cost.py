"""Cost sanity checks for recorded stage usage (design §9.2, §10).

Pi attaches a dollar cost to every assistant message, computed from the resolved model's
price table. A model with no price — a ``models.json`` ``models`` entry that shadows a
catalog model without carrying ``cost``, or a catalog entry the provider does not price —
reports ``$0.0000`` for real token spend. The run then looks free, and an agent's
``max_cost_usd`` ceiling is silently unenforceable, so :func:`is_unpriced` turns that
combination into a warning instead of a quiet zero.
"""

from __future__ import annotations

from typing import Any, Mapping

#: Providers whose models run locally or are self-hosted, where a zero cost is the truth
#: rather than a missing price. Add a provider here when it is configured in
#: ``~/.pi/agent/models.json`` and never bills per token.
LOCAL_PROVIDERS = frozenset({"ollama"})

#: Usage counters that make up a stage's spend when Pi reports no ``total_tokens``.
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read", "cache_write")


def provider_of(model: str) -> str:
    """Provider segment of a qualified model id: ``openrouter/deepseek/x`` -> ``openrouter``."""
    return model.split("/", 1)[0].strip().lower() if model else ""


def total_tokens(usage: Mapping[str, Any] | None) -> int:
    """Tokens a stage spent, preferring Pi's own ``total_tokens``."""
    if not usage:
        return 0
    total = int(usage.get("total_tokens", 0) or 0)
    if total:
        return total
    return sum(int(usage.get(key, 0) or 0) for key in TOKEN_KEYS)


def is_unpriced(model: str, usage: Mapping[str, Any] | None) -> bool:
    """True when a stage spent tokens but recorded no cost at all.

    False for stages that measured nothing, for local providers where free is correct,
    and for any stage whose cost is above zero.
    """
    if not usage or provider_of(model) in LOCAL_PROVIDERS:
        return False
    if float(usage.get("cost_usd", 0.0) or 0.0) != 0.0:
        return False
    return total_tokens(usage) > 0
