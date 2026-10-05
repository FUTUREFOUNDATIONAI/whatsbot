"""Estimated LLM cost with prompt-cache discount.

The cost is an ESTIMATE from the model's listed price (``/models`` of the proxy):
the provider that actually served the call may have charged a different amount.
"""

from __future__ import annotations

from datetime import datetime, timezone

def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0

def current_model_pricing(pricing: dict, now: datetime | None = None) -> dict:
    """Apply an OpenRouter-compatible time-of-day pricing override."""
    selected = dict(pricing or {})
    instant = now or datetime.now(timezone.utc)
    weekday = instant.strftime("%A").lower()
    hhmm = instant.hour * 100 + instant.minute
    for override in pricing.get("overrides", []) if isinstance(pricing, dict) else []:
        days = [str(day).lower() for day in override.get("utc_days", [])]
        if days and weekday not in days:
            continue
        start = int(override.get("utc_start", 0) or 0)
        end = int(override.get("utc_end", 0) or 0)
        if start == end:
            in_window = True
        elif end == 0:
            in_window = hhmm >= start
        elif start < end:
            in_window = start <= hhmm < end
        else:
            in_window = hhmm >= start or hhmm < end
        if in_window:
            selected.update(override)
            break
    return selected

def estimate_cost(pricing: dict | None, prompt_tokens: int, completion_tokens: int,
                  cached_tokens: int = 0, now: datetime | None = None) -> tuple[float, float]:
    """Return ``(cost_usd, saved_usd)`` for one call.

    ``saved_usd`` is the full-price cost minus the cost with the cache discount.
    Without a cache price in ``pricing`` the cached tokens are billed at the full
    input price (no discount, ``saved_usd == 0``).
    """
    if not pricing:
        return 0.0, 0.0
    active = current_model_pricing(pricing, now)
    prompt_price = number(active.get("prompt"))
    completion_price = number(active.get("completion"))
    cache_price = number(active.get("input_cache_read")) or prompt_price
    prompt_tokens = max(int(prompt_tokens or 0), 0)
    completion_tokens = max(int(completion_tokens or 0), 0)
    cached = min(max(int(cached_tokens or 0), 0), prompt_tokens)
    full = prompt_tokens * prompt_price + completion_tokens * completion_price
    cost = (prompt_tokens - cached) * prompt_price + cached * cache_price \
        + completion_tokens * completion_price
    return cost, max(full - cost, 0.0)
