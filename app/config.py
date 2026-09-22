"""Runtime config for the 15-min Kalshi BTC YES/NO bot."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _b(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "open"}


ROOT = Path(__file__).resolve().parents[1]
_load_env_file(ROOT / ".env")
_load_env_file(ROOT / "secrets" / "x_credentials.env")


@dataclass(frozen=True)
class Config:
    host: str = os.environ.get("HOST", "127.0.0.1")
    port: int = _i("PORT", 3000)
    series_ticker: str = os.environ.get("SERIES_TICKER", "KXBTC15M")
    data_dir: Path = Path(os.environ.get("DATA_DIR") or (ROOT / "data"))

    typesafe_api_key: str = os.environ.get("TYPESAFE_API_KEY", "").strip()
    # Pin a versioned JEV id — aliases move and break calibrated thresholds.
    typesafe_model: str = os.environ.get("TYPESAFE_MODEL", "jev-1.13.0")

    # JEV regime-adaptive architecture
    architecture: str = os.environ.get("ARCHITECTURE", "jev-regime-adaptive")
    jev_enabled: bool = _b("JEV_ENABLED", True)
    jev_conf_floor: float = _f("JEV_CONF_FLOOR", 0.55)
    jev_consistency_min: float = _f("JEV_CONSISTENCY_MIN", 0.45)
    jev_escalate_prob: float = _f("JEV_ESCALATE_PROB", 0.55)
    # Desk decides about every 2s. Jev may take 1–2s. Only a miss past this
    # wait is a hold. .env already sets JEV_TIMEOUT_SEC=2.5.
    jev_timeout_sec: float = _f("JEV_TIMEOUT_SEC", 2.5)
    typesafe_base_url: str = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").strip()
    signal_quality_min: float = _f("SIGNAL_QUALITY_MIN", 0.34)
    toxic_flow_max: float = _f("TOXIC_FLOW_MAX", 0.65)
    # The proxy tops out at 3. 2.2 sits under a normal BTC window, so the gate never opens.
    max_vol_proxy: float = _f("MAX_VOL_PROXY", 2.8)
    max_book_spread: float = _f("MAX_BOOK_SPREAD", 0.20)
    max_liquidity_stress: float = _f("MAX_LIQUIDITY_STRESS", 0.85)
    max_stake_usd: float = _f("MAX_STAKE_USD", 25.0)
    max_decision_latency_ms: float = _f("MAX_DECISION_LATENCY_MS", 4000.0)
    layer2_enabled: bool = _b("LAYER2_ENABLED", False)
    layer2_base_url: str = os.environ.get("LAYER2_BASE_URL", "").strip()
    layer2_model: str = os.environ.get("LAYER2_MODEL", "").strip()
    nvidia_api_key: str = os.environ.get("NVIDIA_API_KEY", "").strip()
    nvidia_base_url: str = os.environ.get(
        "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
    ).strip()
    # QuantDinger (OpenByte AI Trading OS) — pointed at Bitcoin
    quantdinger_enabled: bool = _b("QUANTDINGER_ENABLED", True)
    quantdinger_base_url: str = os.environ.get(
        "QUANTDINGER_BASE_URL", "http://127.0.0.1:5000"
    ).strip()
    quantdinger_symbol: str = os.environ.get("QUANTDINGER_SYMBOL", "BTC/USDT").strip()
    quantdinger_in_decisions: bool = _b("QUANTDINGER_IN_DECISIONS", True)
    quantdinger_min_conf: float = _f("QUANTDINGER_MIN_CONF", 0.55)
    quantdinger_min_edge: float = _f("QUANTDINGER_MIN_EDGE", 0.04)
    # BTCC override — Jeremy 2026-09-20: nix hygiene veto.
    # Keep: survive the day · no auto 500x. Take risk to climb $0.03 → $6.
    btcc_hygiene_enforce: bool = _b("BTCC_HYGIENE_ENFORCE", False)
    btcc_risk_mode: str = os.environ.get("BTCC_RISK_MODE", "recover").strip() or "recover"
    recover_target_usd: float = _f("RECOVER_TARGET_USD", 6.0)
    recover_base_stake: float = _f("RECOVER_BASE_STAKE", 0.05)
    twitter_api_key: str = os.environ.get("TWITTER_API_KEY", "").strip()
    twitter_bearer: str = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    twitter_consumer_key: str = os.environ.get("TWITTER_CONSUMER_KEY", "").strip()
    twitter_consumer_secret: str = os.environ.get("TWITTER_CONSUMER_SECRET", "").strip()
    twitter_access_token: str = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
    twitter_access_secret: str = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "").strip()
    twitter_sample: int = _i("TWITTER_SAMPLE", 100)

    stake_usd: float = _f("STAKE_USD", 2.0)
    # Live clip. 5 contracts, or skip if the cash cannot cover that many.
    order_count: float = _f("ORDER_COUNT", 5.0)
    conf_floor: float = _f("CONF_FLOOR", 0.55)
    entry_ceil: float = _f("ENTRY_CEIL", 0.76)
    # Do not buy a 1¢ corpse the book has already priced as the loser.
    entry_floor: float = _f("ENTRY_FLOOR", 0.20)
    # Fire only in the last few minutes. A $20 lead with 14 minutes left is not the settlement.
    entry_max_seconds: float = _f("ENTRY_MAX_SECONDS", 180.0)
    entry_min_seconds: float = _f("ENTRY_MIN_SECONDS", 25.0)
    edge_floor: float = _f("EDGE_FLOOR", 0.0)
    trade_on_lean: bool = _b("TRADE_ON_LEAN", True)
    poll_sec: float = _f("POLL_SEC", 8.0)
    judge_ttl_sec: float = _f("JUDGE_TTL_SEC", 6.0)
    chart_poll_sec: float = _f("CHART_POLL_SEC", 1.0)
    fast_feed_sec: float = _f("FAST_FEED_SEC", 0.6)
    day_stop_usd: float = _f("DAY_STOP_USD", 1_000_000.0)

    # Martingale: double-down until cash >= target, then standard retry stake
    martingale_enabled: bool = _b("MARTINGALE", True)
    martingale_target: float = _f("MARTINGALE_TARGET_USD", 6.0)
    base_stake_usd: float = _f("BASE_STAKE_USD", 0.05)
    retry_stake_usd: float = _f("RETRY_STAKE_USD", 2.0)
    max_doubles: int = _i("MAX_DOUBLES", 4)
    martingale_reserve_keep: float = _f("MARTINGALE_RESERVE_KEEP", 0.92)

    kalshi_api_key_id: str = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    kalshi_private_key_path: str = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
    kalshi_exchange_index: int = _i("KALSHI_EXCHANGE_INDEX", 0)
    live_mark_path: str = os.environ.get("LIVE_MARK_PATH", "").strip()

    coinbase_rest: str = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
    coinbase_ws: str = "wss://ws-feed.exchange.coinbase.com"
    kalshi_public: str = "https://external-api.kalshi.com/trade-api/v2"
    kalshi_trade: str = "https://api.elections.kalshi.com"

    @property
    def live_mark(self) -> Path:
        cands: list[Path] = []
        raw = (self.live_mark_path or "").strip()
        if raw:
            cands.append(Path(raw).expanduser())
            s = raw.replace("\\", "/")
            if len(s) >= 2 and s[1] == ":":
                drive = s[0].lower()
                rest = s.split(":", 1)[1].lstrip("/")
                cands.append(Path(f"/mnt/{drive}/{rest}"))
        cands.append(Path.home() / ".beat15m" / "LIVE_MARK")
        cands.append(Path("/mnt/c/Users/jpana/.beat15m/LIVE_MARK"))
        for c in cands:
            try:
                if c.is_file():
                    return c
            except OSError:
                continue
        return cands[0] if cands else Path.home() / ".beat15m" / "LIVE_MARK"

    @property
    def secrets_dir_candidates(self) -> list[Path]:
        return [
            Path.home() / ".beat15m",
            Path.home() / ".kalshi",
            ROOT / "secrets",
        ]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)

    def day_loss_stop_usd(self) -> float:
        """Settled-loss kill for the UTC day.

        DAY_STOP_USD at 100000 or more is the unset placeholder. The kill is
        then two stakes. A smaller env value is used as written. Wins do not count.
        """
        raw = float(self.day_stop_usd)
        if raw >= 100_000:
            return max(1.0, float(self.stake_usd) * 2.0)
        return raw


config = Config()
config.ensure_dirs()
