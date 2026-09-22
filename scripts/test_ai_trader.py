"""AI-Trader crowd vote ignores copies, other symbols, and a split tape."""
from app.ai_trader import lean_from_signals

NOW = 1_790_023_600.0


def row(agent, side, symbol="BTC", copied=False, age=60):
    return {
        "agent_id": agent,
        "symbol": symbol,
        "side": side,
        "timestamp": NOW - age,
        "content": "[Copied from x] note" if copied else "own note",
    }


def main() -> None:
    bull = lean_from_signals(
        [row(1, "buy"), row(2, "buy"), row(2, "sell"), row(3, "buy"), row(9, "buy", copied=True), row(4, "buy", "ETH")],
        NOW,
    )
    assert bull["lean"] == "YES" and bull["agents"] == 2 or bull["agents"] == 3, bull
    # agent 2 counted once as buy (first). agents 1,2,3 = 3 buys. ETH and copy dropped.
    assert bull["lean"] == "YES" and bull["buys"] == 3 and bull["sells"] == 0, bull

    split = lean_from_signals([row(1, "buy"), row(2, "sell"), row(3, "buy")], NOW)
    assert split["lean"] == "SKIP", split

    stale = lean_from_signals([row(i, "buy", age=4000) for i in range(5)], NOW)
    assert stale["lean"] == "SKIP", stale
    print("ai trader vote ok")


if __name__ == "__main__":
    main()
