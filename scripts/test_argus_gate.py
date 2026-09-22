"""Argus gates: a pretty in-sample run still dies if the vault fails."""
from app.argus_gate import judge_returns


def _book(n: int, ret: float, start: float = 1_700_000_000.0) -> list[tuple[float, float]]:
    return [(start + i * 900, ret) for i in range(n)]


def main() -> None:
    thin = judge_returns(_book(6, 0.1))
    assert thin["promote"] is False, thin

    # Alternating wins that are larger than the losses, across a long span.
    rows = []
    t0 = 1_700_000_000.0
    for i in range(36):
        rows.append((t0 + i * 3600, 0.08 if i % 3 else -0.02))
    good = judge_returns(rows)
    assert good["promote"] is True, good

    bad = judge_returns([(t0 + i * 3600, -0.05 if i % 2 == 0 else 0.01) for i in range(36)])
    assert bad["promote"] is False, bad
    print("argus gate ok", good["reason"])


if __name__ == "__main__":
    main()
