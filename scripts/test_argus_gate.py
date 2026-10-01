"""Argus gates: a pretty in-sample run still dies if the vault fails."""
from app.argus_gate import judge_returns


def _book(n: int, ret: float, start: float = 1_700_000_000.0) -> list[tuple[float, float]]:
    return [(start + i * 900, ret) for i in range(n)]


def main() -> None:
    thin = judge_returns(_book(12, 0.2))
    assert thin["promote"] is False, thin
    assert "100" in thin["reason"], thin

    # Two winning trades for each small loss, long enough for a verdict.
    rows = []
    t0 = 1_700_000_000.0
    for i in range(120):
        rows.append((t0 + i * 3600, 0.08 if i % 3 else -0.02))
    good = judge_returns(rows)
    assert good["promote"] is True, good
    assert good["validator"]["gates"]["t_stat"]["value"] > 3.0, good

    bad = judge_returns([(t0 + i * 3600, -0.05 if i % 2 == 0 else 0.01) for i in range(120)])
    assert bad["promote"] is False, bad

    # Strong early, dead at the end. The newest fold is the weak one.
    faded = [(t0 + i * 3600, 0.10 if i < 96 else -0.08) for i in range(120)]
    late = judge_returns(faded)
    assert late["promote"] is False, late
    assert late["walk_forward"]["pass"] is False, late
    print("argus gate ok", good["reason"])


if __name__ == "__main__":
    main()
