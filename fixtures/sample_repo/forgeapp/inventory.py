"""Stock reservation logic."""


class OutOfStock(Exception):
    pass


def reserve(stock: dict[str, int], sku: str, qty: int) -> dict[str, int]:
    """Return a new stock map with qty reserved; never mutate the input."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    available = stock.get(sku, 0)
    if available < qty:
        raise OutOfStock(sku)
    updated = dict(stock)
    updated[sku] = available - qty
    return updated
