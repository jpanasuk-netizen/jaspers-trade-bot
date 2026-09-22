"""Side gate: do not flip, do not buy a corpse, do not fire at the open."""
from app.spin import context_votes, live_entry_block, tape_side


def main() -> None:
    assert tape_side(100.0, 90.0) == "YES"
    assert tape_side(90.0, 100.0) == "NO"
    assert tape_side(100.0, 100.0) is None

    book = {"yes_ask": 0.32, "no_ask": 0.69}
    # Panel agrees, so 14 minutes left is allowed.
    early = live_entry_block("NO", book, 881, 80.0, 100.0)
    assert early is None, early

    # Jev/cheap side fights a spot that is below the open
    fight = live_entry_block("YES", book, 100, 80.0, 100.0)
    assert fight and "fights the tape" in fight, fight

    # 1¢ corpse
    corpse = live_entry_block("YES", {"yes_ask": 0.015, "no_ask": 0.99}, 100, 110.0, 100.0)
    assert corpse and "floor" in corpse, corpse

    # Last few seconds are still inside the window when the panel agrees.
    late = live_entry_block("NO", book, 7, 80.0, 100.0)
    assert late is None, late

    # Tape side at any point in the window. Book mid is the cheap YES, so the book votes NO.
    ok = live_entry_block("NO", book, 100, 80.0, 100.0)
    assert ok is None, ok

    # Spot says YES, but the book, QuantDinger, and flow all say NO.
    against = {
        "yes_ask": 0.40,
        "yes_bid": 0.36,
        "no_ask": 0.62,
    }
    panel = {
        "quantdinger": {"lean": "NO", "fair_yes": 0.35},
        "layer1": {"ofi_proxy": -0.6, "regime": "trending"},
        "btcc": {"lean": "SKIP", "conf": 0.0},
    }
    blocked = live_entry_block("YES", against, 800, 110.0, 100.0, panel)
    assert blocked and "context disagrees" in blocked, blocked
    votes = {v["src"]: v["side"] for v in context_votes(panel, against)}
    assert votes["book"] == "NO" and votes["quantdinger"] == "NO" and votes["ofi"] == "NO"

    # Same window, but the panel agrees with YES.
    with_yes = {
        "quantdinger": {"lean": "YES", "fair_yes": 0.70},
        "layer1": {"ofi_proxy": 0.5, "regime": "trending"},
        "btcc": {"lean": "YES", "conf": 0.7},
        "microstructure": {"rsi_14": 55},
    }
    favored = {"yes_ask": 0.62, "yes_bid": 0.58, "no_ask": 0.40}
    allowed = live_entry_block("YES", favored, 100, 110.0, 100.0, with_yes)
    assert allowed is None, allowed

    # A regime break is its own skip, even when the side matches the tape.
    crisis = live_entry_block(
        "YES", favored, 100, 110.0, 100.0, {"layer1": {"regime": "crisis"}}
    )
    assert crisis and "crisis" in crisis, crisis
    print("side gate ok")


if __name__ == "__main__":
    main()
