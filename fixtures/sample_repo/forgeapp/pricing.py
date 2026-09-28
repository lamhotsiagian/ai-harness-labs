"""Pricing helpers used by the checkout service."""


def apply_discount(price: float, pct: float) -> float:
    """Return price after a percentage discount (pct in 0..100)."""
    if not 0 <= pct <= 100:
        raise ValueError("pct must be within 0..100")
    return round(price * (1 - pct / 100), 2)


def total_with_tax(items: list[float], rate: float) -> float:
    """Sum item prices and apply a tax rate such as 0.11 for 11 percent."""
    subtotal = sum(items)
    return round(subtotal * (1 + rate), 2)
