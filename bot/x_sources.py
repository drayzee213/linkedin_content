"""X/Twitter-Suche nach Video-Posts. Zwei austauschbare Quellen, gleiche Ausgabe.

Jeder Kandidat ist ein dict:
  id, url, text, author (Handle), author_name, likes, reposts, views,
  created (Unix-Sekunden), duration (Sekunden), video_url (direkte mp4-URL)
"""
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

TIMEOUT = 30


def _best_mp4(variants: list, bitrate_key: str) -> str | None:
    mp4 = [v for v in variants or [] if v.get("content_type") == "video/mp4" and v.get("url")]
    if not mp4:
        return None
    return max(mp4, key=lambda v: v.get(bitrate_key) or 0)["url"]


def _all_queries(cfg: dict) -> list[str]:
    queries = list(cfg.get("queries") or [])
    accounts = cfg.get("accounts") or []
    for i in range(0, len(accounts), 10):
        queries.append("(" + " OR ".join(f"from:{a}" for a in accounts[i:i + 10]) + ")")
    return queries


# ---------- Offizielle X API v2 ----------

def parse_official(payload: dict) -> list[dict]:
    inc = payload.get("includes") or {}
    media = {m["media_key"]: m for m in inc.get("media", [])}
    users = {u["id"]: u for u in inc.get("users", [])}
    out = []
    for t in payload.get("data") or []:
        keys = (t.get("attachments") or {}).get("media_keys") or []
        video = next((media[k] for k in keys if media.get(k, {}).get("type") == "video"), None)
        if not video:
            continue
        url = _best_mp4(video.get("variants"), "bit_rate")
        if not url:
            continue
        user = users.get(t.get("author_id"), {})
        pm = t.get("public_metrics") or {}
        created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).timestamp()
        out.append({
            "id": t["id"],
            "url": f"https://x.com/{user.get('username', 'i')}/status/{t['id']}",
            "text": (t.get("note_tweet") or {}).get("text") or t.get("text", ""),
            "author": user.get("username", ""),
            "author_name": user.get("name", ""),
            "likes": pm.get("like_count", 0),
            "reposts": pm.get("retweet_count", 0),
            "views": pm.get("impression_count", 0),
            "created": int(created),
            "duration": (video.get("duration_ms") or 0) / 1000,
            "video_url": url,
        })
    return out


def search_official(cfg: dict) -> list[dict]:
    token = os.environ["X_BEARER_TOKEN"]
    out = []
    for q in _all_queries(cfg):
        r = requests.get(
            "https://api.x.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "query": f"({q}) has:videos -is:retweet -is:reply lang:{cfg['tweet_lang']}",
                "max_results": max(10, min(100, cfg["max_results_per_query"])),
                "sort_order": "relevancy",
                "tweet.fields": "created_at,public_metrics,attachments,note_tweet",
                "expansions": "attachments.media_keys,author_id",
                "media.fields": "type,duration_ms,variants",
                "user.fields": "username,name",
            },
            timeout=TIMEOUT,
        )
        if r.status_code == 429:
            print("X API: Rate-Limit erreicht, breche Suche ab.")
            break
        r.raise_for_status()
        out += parse_official(r.json())
    return out


# ---------- Drittanbieter: twitterapi.io ----------

def parse_thirdparty(payload: dict) -> list[dict]:
    out = []
    for t in payload.get("tweets") or []:
        medias = (t.get("extendedEntities") or {}).get("media") or []
        video = next((m for m in medias if m.get("type") == "video"), None)
        if not video:
            continue
        info = video.get("video_info") or {}
        url = _best_mp4(info.get("variants"), "bitrate")
        if not url:
            continue
        author = t.get("author") or {}
        try:
            created = parsedate_to_datetime(t.get("createdAt", "")).timestamp()
        except (TypeError, ValueError):
            created = time.time()
        out.append({
            "id": str(t["id"]),
            "url": t.get("url") or f"https://x.com/i/status/{t['id']}",
            "text": t.get("text", ""),
            "author": author.get("userName", ""),
            "author_name": author.get("name", ""),
            "likes": t.get("likeCount", 0),
            "reposts": t.get("retweetCount", 0),
            "views": t.get("viewCount", 0),
            "created": int(created),
            "duration": (info.get("duration_millis") or 0) / 1000,
            "video_url": url,
        })
    return out


def search_thirdparty(cfg: dict) -> list[dict]:
    key = os.environ["TWITTERAPI_IO_KEY"]
    since = datetime.fromtimestamp(time.time() - cfg["max_age_hours"] * 3600, timezone.utc)
    out = []
    for q in _all_queries(cfg):
        query = (f"({q}) filter:native_video -filter:retweets -filter:replies "
                 f"lang:{cfg['tweet_lang']} min_faves:{cfg['min_likes']} "
                 f"since:{since:%Y-%m-%d}")
        r = requests.get(
            "https://api.twitterapi.io/twitter/tweet/advanced_search",
            headers={"X-API-Key": key},
            params={"query": query, "queryType": "Top"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        out += parse_thirdparty(r.json())
    return out


# ---------- Gemeinsame Filterung ----------

def score(c: dict) -> float:
    """Engagement pro Stunde: frische Posts mit viel Resonanz zuerst."""
    age_h = max(1.0, (time.time() - c["created"]) / 3600)
    return (c["likes"] + 3 * c["reposts"]) / age_h ** 0.7


def filter_candidates(cands: list[dict], cfg: dict, seen: set[str]) -> list[dict]:
    blocked = {a.lower().lstrip("@") for a in cfg.get("blocked_accounts") or []}
    min_created = time.time() - cfg["max_age_hours"] * 3600
    uniq = {}
    for c in cands:
        if c["id"] in seen or c["id"] in uniq:
            continue
        if c["author"].lower() in blocked or c["created"] < min_created:
            continue
        if c["likes"] < cfg["min_likes"]:
            continue
        if c["duration"] and not cfg["video_min_seconds"] <= c["duration"] <= cfg["video_max_seconds"]:
            continue
        uniq[c["id"]] = c
    return sorted(uniq.values(), key=score, reverse=True)


def search(cfg: dict) -> list[dict]:
    source = cfg.get("x_source", "official")
    if source == "official":
        return search_official(cfg)
    if source == "thirdparty":
        return search_thirdparty(cfg)
    raise SystemExit(f"Unbekannte x_source: {source}")
