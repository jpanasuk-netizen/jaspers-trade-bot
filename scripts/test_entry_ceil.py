"""ENTRY_CEIL is a hard abort. 96¢ tickets must not quote or place."""
from app.config import config
from app.kalshi_live import ask_over_ceil, budget_quote, cheapest_affordable, pricey_reason, sized_quote
from app.spin import live_entry_block


def main() -> None:
    ceil = float(config.entry_ceil)
    assert ask_over_ceil(0.96) is True
    assert ask_over_ceil(ceil) is False
    assert pricey_reason("NO", 0.96)
    assert pricey_reason("YES", 0.50) is None

    fat = {"yes_ask": 0.96, "no_ask": 0.96, "yes_bid": 0.94, "no_bid": 0.94}
    assert budget_quote("NO", fat, 5.0, 20.0) is None
    assert sized_quote("YES", fat, 20.0) is None
    assert cheapest_affordable(fat, 20.0) is None

    ok = {"yes_ask": 0.40, "no_ask": 0.61, "yes_bid": 0.38, "no_bid": 0.59}
    clip = budget_quote("YES", ok, 2.0, 20.0)
    assert clip is not None and clip["ask"] <= ceil + 1e-9, clip

    blocked = live_entry_block("NO", fat, 90, 80.0, 100.0)
    assert blocked and "SKIP_PRICEY" in blocked, blocked
    print("entry ceil ok", ceil)


if __name__ == "__main__":
    main()
