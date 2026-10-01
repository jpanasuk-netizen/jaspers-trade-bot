"""Causal HMM filter and the code size ceiling. No smoothed probabilities."""
from app.regime import filtered_regime, jev_size_tier, regime_router, reset_filter


def _run(spread: float, n: int = 8, seconds: float = 400.0) -> list[dict]:
    rows = []
    for _ in range(n):
        rows.append(filtered_regime(0.02, 0.04, spread, seconds))
    return rows


def main() -> None:
    reset_filter()
    quiet = _run(0.01)
    assert quiet[-1]["prob_kind"] == "filtered"
    assert "smoothed" not in quiet[-1]
    assert abs(sum(quiet[-1]["regime_probs"].values()) - 1.0) < 0.02
    assert quiet[-1]["regime"] == "quiet", quiet[-1]

    reset_filter()
    thin = _run(0.14)
    assert thin[-1]["regime"] == "thin_liquidity", thin[-1]

    reset_filter()
    early_tight = []
    for i in range(6):
        spread = 0.01 if i < 3 else 0.14
        early_tight.append(filtered_regime(0.02, 0.04, spread, 400)["regime_probs"]["thin_liquidity"])
    reset_filter()
    early_wide = []
    for i in range(6):
        spread = 0.14 if i < 3 else 0.01
        early_wide.append(filtered_regime(0.02, 0.04, spread, 400)["regime_probs"]["thin_liquidity"])
    assert early_tight != early_wide

    full = regime_router(
        {"regime": "quiet", "pin_overlay": False, "regime_conf": 0.8},
        side="YES",
        conf=0.9,
        order_budget=5.0,
    )
    assert full["jev_tier"] == 3 and full["ceiling"] == 3 and full["final_tier"] == 3
    assert abs(full["budget_usd"] - 5.0) < 1e-9

    informed = regime_router(
        {"regime": "informed_flow", "pin_overlay": False},
        side="YES",
        conf=0.9,
        order_budget=5.0,
    )
    assert informed["jev_tier"] == 3 and informed["regime_ceiling"] == 2
    assert informed["final_tier"] == 2
    assert abs(informed["budget_usd"] - round(5.0 * 2 / 3, 4)) < 1e-9

    capped = regime_router(
        {"regime": "thin_liquidity", "pin_overlay": False},
        side="NO",
        conf=0.95,
        order_budget=5.0,
    )
    assert capped["final_tier"] == 1
    assert abs(capped["budget_usd"] - round(5.0 / 3, 4)) < 1e-9

    pinned = regime_router(
        {"regime": "quiet", "pin_overlay": True},
        side="YES",
        conf=0.95,
        order_budget=5.0,
    )
    assert pinned["ceiling"] == 1 and pinned["final_tier"] == 1

    mid = regime_router(
        {"regime": "quiet", "pin_overlay": False},
        side="YES",
        conf=0.61,
        order_budget=5.0,
    )
    assert mid["jev_tier"] == 2 and mid["final_tier"] == 2
    assert jev_size_tier(0.5, "YES") == 1
    assert jev_size_tier(0.9, "SKIP") == 0

    reset_filter()
    assert filtered_regime(0.01, 0.02, 0.01, 30)["pin_overlay"] is True
    assert filtered_regime(0.01, 0.02, 0.01, 120)["pin_overlay"] is False
    print("regime router ok")


if __name__ == "__main__":
    main()
