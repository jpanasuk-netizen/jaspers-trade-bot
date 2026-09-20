"""Jev-X social sentiment pipeline (portable). Optional TwitterAPI.io key."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import config

FEAR_KEYWORDS = {
    "crash", "dump", "liquidation", "sell", "selling", "dead", "bear", "bearish",
    "scam", "rekt", "drop", "loss", "bleeding", "panic", "fear", "down", "dip", "fall",
}
GREED_KEYWORDS = {
    "pump", "moon", "ath", "buy", "buying", "gem", "bull", "bullish", "breakout",
    "rally", "gain", "accumulate", "rocket", "up", "long", "hold", "squeeze",
}

_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "symbol": None,
    "stats": None,
    "tweets": [],
    "is_mock": True,
    "source": "none",
}

TWITTER_API_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"
REDDIT_URLS = {
    "BTC": [
        "https://www.reddit.com/r/Bitcoin/hot.json?limit=50",
        "https://www.reddit.com/r/CryptoCurrency/hot.json?limit=50",
    ],
}


def process_tweets(tweets: list[dict[str, Any]]) -> dict[str, Any]:
    """Tier-1 stats from Jev-X (engagement, diversity, polarity)."""
    if not tweets:
        return {
            "sample_size": 0,
            "unique_authors_count": 0,
            "author_diversity_pct": 0.0,
            "total_likes": 0,
            "total_retweets": 0,
            "avg_engagement": 0.0,
            "fear_mentions": 0,
            "greed_mentions": 0,
            "polarity_score": 0.0,
            "sentiment_label": "Neutral / Mixed",
            "stratified_sample": [],
        }

    total_likes = 0
    total_retweets = 0
    authors: set[str] = set()
    fear_count = 0
    greed_count = 0

    for t in tweets:
        total_likes += int(t.get("likes") or 0)
        total_retweets += int(t.get("retweets") or 0)
        username = (t.get("author_username") or "unknown").lower()
        authors.add(username)
        words = set((t.get("text") or "").lower().replace("$", "").replace("#", "").split())
        fear_count += len(words & FEAR_KEYWORDS)
        greed_count += len(words & GREED_KEYWORDS)

    sample_size = len(tweets)
    unique_authors = len(authors)
    diversity_pct = round((unique_authors / sample_size) * 100.0, 1)
    avg_engagement = round((total_likes + total_retweets * 2) / sample_size, 1)
    total_polar = fear_count + greed_count
    polarity = round((greed_count - fear_count) / total_polar, 2) if total_polar else 0.0

    if polarity <= -0.4:
        label = "Extreme Panic / Capitulation"
    elif polarity < -0.1:
        label = "Cautious / Bearish"
    elif polarity <= 0.1:
        label = "Neutral / Mixed"
    elif polarity < 0.4:
        label = "Optimistic / Bullish"
    else:
        label = "Euphoric / Greedy"

    sorted_by_eng = sorted(
        tweets,
        key=lambda x: int(x.get("likes") or 0) + int(x.get("retweets") or 0) * 2,
        reverse=True,
    )
    seen: set[str] = set()
    stratified: list[dict[str, Any]] = []
    for t in sorted_by_eng[:25]:
        tid = str(t.get("id") or id(t))
        if tid in seen:
            continue
        seen.add(tid)
        stratified.append({
            "author": t.get("author_username"),
            "text": (t.get("text") or "")[:240],
            "likes": t.get("likes"),
            "type": "high_engagement",
        })
    for t in tweets[:25]:
        tid = str(t.get("id") or id(t))
        if tid in seen:
            continue
        seen.add(tid)
        stratified.append({
            "author": t.get("author_username"),
            "text": (t.get("text") or "")[:240],
            "likes": t.get("likes"),
            "type": "latest_breaking",
        })

    return {
        "sample_size": sample_size,
        "unique_authors_count": unique_authors,
        "author_diversity_pct": diversity_pct,
        "total_likes": total_likes,
        "total_retweets": total_retweets,
        "avg_engagement": avg_engagement,
        "fear_mentions": fear_count,
        "greed_mentions": greed_count,
        "polarity_score": polarity,
        "sentiment_label": label,
        "stratified_sample": stratified[:20],
    }


def _mock_tweets(symbol: str, n: int = 24) -> list[dict[str, Any]]:
    """Offline stand-in so the HUD always has a sentiment block."""
    base = [
        (f"{symbol} looking heavy here", 120, 18, "bear_watch"),
        (f"accumulating more {symbol} on this dip", 410, 55, "bull_desk"),
        (f"liquidation cascade on {symbol} perps, ugly", 890, 210, "flow_watcher"),
        (f"{symbol} breakout if we reclaim the open", 260, 40, "chart_nerd"),
        (f"panic is too strong on {symbol} — squeeze risk", 330, 70, "squeeze_scout"),
        (f"nothing to do on {symbol} until the window settles", 40, 6, "range_trader"),
    ]
    out = []
    for i in range(min(n, len(base) * 2)):
        text, likes, rts, author = base[i % len(base)]
        out.append({
            "id": f"mock-{symbol}-{i}",
            "author_username": author,
            "text": text,
            "likes": likes + i,
            "retweets": rts,
            "replies": 3,
        })
    return out


def _x_api_fetch(symbol: str, target: int) -> list[dict[str, Any]]:
    """Official X API v2 recent search with Bearer token (raw or URL-decoded)."""
    bearer = config.twitter_bearer
    if not bearer:
        return []
    # Some operator pastes are URL-encoded; try both forms.
    bearers = [bearer]
    decoded = urllib.parse.unquote(bearer)
    if decoded != bearer:
        bearers.append(decoded)
    sym = symbol.upper().replace("$", "")
    names = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana"}
    full = names.get(sym, sym)
    query = f"(${sym} OR {full}) lang:en -is:retweet"
    max_results = 10 if target < 10 else min(100, max(10, target))
    params = {
        "query": query,
        "max_results": str(max_results),
        "tweet.fields": "public_metrics,created_at,author_id,lang",
        "expansions": "author_id",
        "user.fields": "username,public_metrics",
    }
    url = "https://api.twitter.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
    last_err = None
    for bearer_try in bearers:
        headers = {
            "Authorization": f"Bearer {bearer_try}",
            "User-Agent": "jev-15m-kalshi-bot/1.0",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            data = None
    else:
        print(f"[sentiment] X API failed: {last_err}", flush=True)
        # OAuth1 fallback using consumer + access tokens
        return _x_oauth1_fetch(sym, target, full)

    if not isinstance(data, dict):
        return _x_oauth1_fetch(sym, target, full)

    users = {}
    for u in (data.get("includes") or {}).get("users") or []:
        users[str(u.get("id"))] = u.get("username") or "x_user"
    tweets: list[dict[str, Any]] = []
    for t in data.get("data") or []:
        metrics = t.get("public_metrics") or {}
        uid = str(t.get("author_id") or "")
        tweets.append({
            "id": str(t.get("id") or ""),
            "author_username": users.get(uid) or uid or "x_user",
            "text": t.get("text") or "",
            "likes": int(metrics.get("like_count") or 0),
            "retweets": int(metrics.get("retweet_count") or 0),
            "replies": int(metrics.get("reply_count") or 0),
            "created_at": t.get("created_at"),
        })
    return tweets[:target]


def _oauth1_header(method: str, url: str) -> str:
    """Minimal OAuth1 header for app+user creds (no external oauth lib)."""
    import base64
    import hashlib
    import hmac
    import secrets as _secrets
    import time as _time

    ck = urllib.parse.unquote(config.twitter_consumer_key)
    cs = urllib.parse.unquote(config.twitter_consumer_secret)
    at = urllib.parse.unquote(config.twitter_access_token)
    ats = urllib.parse.unquote(config.twitter_access_secret)
    oauth = {
        "oauth_consumer_key": ck,
        "oauth_nonce": _secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(_time.time())),
        "oauth_token": at,
        "oauth_version": "1.0",
    }
    # parse query params for signature base
    parsed = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    params = {**q, **oauth}
    enc = lambda s: urllib.parse.quote(str(s), safe="")
    param_str = "&".join(f"{enc(k)}={enc(params[k])}" for k in sorted(params))
    base = "&".join([method.upper(), enc(parsed.scheme + "://" + parsed.netloc + parsed.path), enc(param_str)])
    signing_key = f"{enc(cs)}&{enc(ats)}"
    digest = hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode()
    header_params = {k: oauth[k] for k in oauth}
    auth = "OAuth " + ", ".join(f'{k}="{urllib.parse.quote(str(v), safe="")}"' for k, v in sorted(header_params.items()))
    return auth


def _x_oauth1_fetch(sym: str, target: int, full: str) -> list[dict[str, Any]]:
    if not (config.twitter_consumer_key and config.twitter_access_token):
        return []
    query = f"(${sym} OR {full}) lang:en -is:retweet"
    max_results = 10 if target < 10 else min(100, max(10, target))
    params = {
        "query": query,
        "max_results": str(max_results),
        "tweet.fields": "public_metrics,author_id,created_at",
        "expansions": "author_id",
        "user.fields": "username",
    }
    url = "https://api.twitter.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
    try:
        auth = _oauth1_header("GET", url)
        req = urllib.request.Request(url, headers={
            "Authorization": auth,
            "User-Agent": "jev-15m-kalshi-bot/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[sentiment] X OAuth1 failed: {exc}", flush=True)
        return []
    users = {}
    for u in (data.get("includes") or {}).get("users") or []:
        users[str(u.get("id"))] = u.get("username") or "x_user"
    out = []
    for t in data.get("data") or []:
        m = t.get("public_metrics") or {}
        uid = str(t.get("author_id") or "")
        out.append({
            "id": str(t.get("id") or ""),
            "author_username": users.get(uid) or "x_user",
            "text": t.get("text") or "",
            "likes": int(m.get("like_count") or 0),
            "retweets": int(m.get("retweet_count") or 0),
            "replies": int(m.get("reply_count") or 0),
        })
    return out[:target]


def _twitter_fetch(symbol: str, target: int) -> list[dict[str, Any]]:
    """X API v2 first, then TwitterAPI.io advanced_search (Jev-X)."""
    tweets = _x_api_fetch(symbol, target)
    if tweets:
        return tweets
    key = config.twitter_api_key
    if not key:
        return []
    sym = symbol.upper().replace("$", "")
    names = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana"}
    full = names.get(sym, sym)
    if full == sym:
        query = f"${sym} lang:en -is:retweet min_faves:2"
    else:
        query = f"(${sym} OR {full}) lang:en -is:retweet min_faves:2"
    params = {"query": query, "queryType": "Latest"}
    url = TWITTER_API_URL + "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/json",
        "X-API-Key": key,
        "User-Agent": "jev-15m-kalshi-bot/1.0",
    }
    req = urllib.request.Request(url, headers=headers)
    tweets: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = data.get("tweets") or data.get("data") or []
        for t in rows[:target]:
            author = t.get("author") or {}
            if not isinstance(author, dict):
                author = {}
            tweets.append({
                "id": str(t.get("id") or t.get("id_str") or ""),
                "author_username": author.get("userName") or author.get("username") or t.get("author_username") or "x_user",
                "text": t.get("text") or t.get("full_text") or "",
                "likes": int(t.get("likeCount") or t.get("likes") or 0),
                "retweets": int(t.get("retweetCount") or t.get("retweets") or 0),
                "replies": int(t.get("replyCount") or t.get("replies") or 0),
            })
    except Exception as exc:  # noqa: BLE001
        print(f"[sentiment] twitterapi.io failed: {exc}", flush=True)
        return []
    return tweets


def _hn_fetch(symbol: str, target: int) -> list[dict[str, Any]]:
    """Hacker News Algolia — real public posts mentioning the asset."""
    sym = symbol.upper().replace("$", "")
    names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    q = names.get(sym, sym.lower())
    url = (
        "https://hn.algolia.com/api/v1/search_by_date?"
        + urllib.parse.urlencode({"query": q, "tags": "story", "hitsPerPage": min(50, max(10, target))})
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "jev-15m-kalshi-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[sentiment] HN failed: {exc}", flush=True)
        return []
    out = []
    for h in data.get("hits") or []:
        title = h.get("title") or h.get("story_title") or ""
        if not title:
            continue
        out.append({
            "id": str(h.get("objectID") or h.get("story_id") or ""),
            "author_username": h.get("author") or "hn",
            "text": title,
            "likes": int(h.get("points") or 0),
            "retweets": int(h.get("num_comments") or 0),
            "replies": int(h.get("num_comments") or 0),
        })
    return out[:target]


def _reddit_fetch(symbol: str, target: int) -> list[dict[str, Any]]:
    """Real public Reddit sample when TwitterAPI.io key is missing."""
    urls = REDDIT_URLS.get(symbol.upper().replace("$", ""), REDDIT_URLS["BTC"])
    headers = {
        "Accept": "application/json",
        "User-Agent": "jev-15m-kalshi-bot/1.0 (research; contact: local)",
    }
    out: list[dict[str, Any]] = []
    for url in urls:
        if len(out) >= target:
            break
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            children = ((data.get("data") or {}).get("children")) or []
            for c in children:
                d = c.get("data") or {}
                text = (d.get("title") or "") + " " + (d.get("selftext") or "")
                out.append({
                    "id": str(d.get("id") or ""),
                    "author_username": d.get("author") or "redditor",
                    "text": text.strip()[:500],
                    "likes": int(d.get("ups") or d.get("score") or 0),
                    "retweets": int(d.get("num_comments") or 0),
                    "replies": int(d.get("num_comments") or 0),
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[sentiment] reddit failed {url}: {exc}", flush=True)
            continue
    return out[:target]


def get_sentiment(symbol: str = "BTC", force: bool = False) -> dict[str, Any]:
    """Cached sentiment snapshot for the HUD / judge."""
    global _CACHE
    now = time.time()
    if (
        not force
        and _CACHE.get("stats") is not None
        and _CACHE.get("symbol") == symbol
        and now - float(_CACHE.get("ts") or 0) < 180
    ):
        return {
            "ok": True,
            "symbol": symbol,
            "stats": _CACHE["stats"],
            "is_mock": _CACHE.get("is_mock", True),
            "source": _CACHE.get("source", "unknown"),
            "tweets_sample": _CACHE.get("tweets", [])[:8],
            "cached": True,
        }

    source = "mock"
    tweets = _twitter_fetch(symbol, config.twitter_sample)
    if tweets:
        source = "x_api_v2" if (config.twitter_bearer or config.twitter_access_token) else "twitterapi.io"
    else:
        tweets = _hn_fetch(symbol, max(25, config.twitter_sample // 2))
        if tweets:
            source = "hn_public"
        else:
            tweets = _reddit_fetch(symbol, max(40, config.twitter_sample // 2))
            if tweets:
                source = "reddit_public"
    is_mock = len(tweets) == 0
    if is_mock:
        tweets = _mock_tweets(symbol)
        source = "mock"
    stats = process_tweets(tweets)
    stats["source"] = source
    # attach Jev-X microstructure for the judge (RSI / funding / OI)
    try:
        from .micro import fetch_microstructure

        micro = fetch_microstructure(symbol)
    except Exception:  # noqa: BLE001
        micro = {}
    _CACHE = {
        "ts": now,
        "symbol": symbol,
        "stats": stats,
        "tweets": stats.get("stratified_sample", []),
        "is_mock": is_mock,
        "source": source,
        "micro": micro,
    }
    return {
        "ok": True,
        "symbol": symbol,
        "stats": stats,
        "is_mock": is_mock,
        "source": source,
        "micro": micro,
        "tweets_sample": _CACHE["tweets"][:8],
        "cached": False,
    }
