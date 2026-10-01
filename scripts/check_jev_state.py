"""One-shot check: Jev state stays numeric, and a missing Layer-2 does not steal the route."""
from app.jev_layer import build_jev_state
from app.config import config

state = build_jev_state(
    {"desks": {"note": "inputs"}, "polarity_score": 0.1, "social_sample": 3},
    [{"text": "should not be in state"}],
)
assert "representative_tweets" not in state
assert "btc_listings" not in state
assert state["desks"]["note"] == "inputs"
assert state["social_stats"]["sample_size"] == 3
assert config.layer2_enabled is False
print("jev state ok")
