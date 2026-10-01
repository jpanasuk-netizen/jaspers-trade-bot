from app.config import config
from app.kalshi_live import sized_quote

assert config.order_count == 5
full = sized_quote("YES", {"yes_ask": 0.50, "no_ask": 0.51}, 20, max_count=config.order_count)
assert full and full["count"] == 5
short = sized_quote("YES", {"yes_ask": 0.50, "no_ask": 0.51}, 1.2, max_count=config.order_count)
assert short and short["count"] < 5
print("order count", config.order_count, "full", full["count"], "short", short["count"])
