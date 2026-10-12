"""Unit prices for the cost report.

Source: Azure retail prices API (prices.azure.com), region swedencentral, EUR,
pay-as-you-go, looked up on 2026-10-11. Model prices are the regional
(Standard) rates, which is the deployment type in deploy/ai.bicep. Prices
change: look them up again before quoting a cost.
"""

from decimal import Decimal

PRICES_AS_OF = "2026-10-11"

# EUR per 1,000 pages
PAGE_PRICES = {
    "prebuilt-read": Decimal("1.3200"),
    "prebuilt-invoice": Decimal("8.7997"),
}
# EUR per 1,000 tokens: (input, output)
TOKEN_PRICES = {
    "gpt-4.1": (Decimal("0.0021"), Decimal("0.0085")),
    "gpt-4.1-mini": (Decimal("0.0004"), Decimal("0.0017")),
    "text-embedding-3-large": (Decimal("0.0001"), Decimal("0")),
}


def call_cost(*, model: str, pages: int, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Cost of one call in EUR, or None when the model has no known price."""
    if model in PAGE_PRICES:
        return PAGE_PRICES[model] * pages / 1000
    if model in TOKEN_PRICES:
        input_price, output_price = TOKEN_PRICES[model]
        return (input_price * input_tokens + output_price * output_tokens) / 1000
    return None
