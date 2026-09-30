"""Ask the local Jev harness before a research command runs. Does not trade."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/home/jpanasuk/jev-harness")

from jev_harness import decide_command, load_pinned, route_task, score_chunks  # noqa: E402

QUESTION = (
    "Research and backtest ETH 15-minute up or down candle strategies. "
    "Payout is 1.8x with a 0.06 percent fee. Keep a win rate above 57 percent. "
    "Hide one third of the candles and validate survivors once. "
    "Use half Kelly sizing. Log the study and push it to the Kalshi 15-minute desk. "
    "Do not pick a Kalshi YES or NO."
)

RULES = [
    {
        "name": "no-kalshi-pick",
        "glob": "*.py",
        "text": (
            "Do not pick YES or NO. Do not edit app/spin.py, app/jev_layer.py, "
            "or the order path. This ETH study is a log pushed to the desk repo."
        ),
    },
    {
        "name": "no-secrets",
        "glob": "*key*",
        "text": "Never read or commit secrets, .env, or key files.",
    },
]


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    cwd = "/home/jpanasuk/jev-15m-kalshi-bot"
    decision = decide_command(command, cwd) if command else {"decision": "skip", "reason": "no command"}
    route = route_task(QUESTION, [cwd + "/research/eth15m/strategies.py"])
    pinned = load_pinned(
        RULES,
        [
            cwd + "/research/eth15m/strategies.py",
            cwd + "/secrets/key_id.txt",
        ],
    )
    chunks = score_chunks(
        QUESTION,
        [
            {"id": "question", "text": QUESTION},
            {
                "id": "desk-scope",
                "text": (
                    "The live desk trades Kalshi KXBTC15M only. Jev picks the side. "
                    "ETH 15-minute research is a logged study, not an order."
                ),
            },
            {
                "id": "launcher-notes",
                "text": "Windows launcher rebuild notes, proxy ports, and exe paths.",
            },
        ],
    )
    print(json.dumps({"decision": decision, "route": route, "pinned": pinned, "chunks": chunks}, indent=2))


if __name__ == "__main__":
    main()
