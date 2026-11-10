import time

import pytest

from bot import approve, common, linkedin, llm, telegram, x_sources

CFG = common.load_config()


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")


def cand(**kw):
    c = {"id": "1", "url": "https://x.com/a/status/1", "text": "Cool demo", "author": "a",
         "author_name": "A", "likes": 500, "reposts": 50, "views": 9, "created": int(time.time()) - 3600,
         "duration": 30, "video_url": "https://v/x.mp4", "post_text": "Hook\n\nText", "hashtags": ["#KI"],
         "reason": "r", "msg_id": 7, "sent": int(time.time())}
    c.update(kw)
    return c


def test_parse_official_picks_best_mp4():
    payload = {"data": [{"id": "1", "text": "hi", "author_id": "u", "created_at": "2026-11-10T08:00:00.000Z",
                         "public_metrics": {"like_count": 5, "retweet_count": 1},
                         "attachments": {"media_keys": ["m"]}},
                        {"id": "2", "text": "no video", "author_id": "u", "created_at": "2026-11-10T08:00:00.000Z"}],
               "includes": {"users": [{"id": "u", "username": "bob", "name": "Bob"}],
                            "media": [{"media_key": "m", "type": "video", "duration_ms": 12000, "variants": [
                                {"content_type": "application/x-mpegURL", "url": "x.m3u8"},
                                {"content_type": "video/mp4", "bit_rate": 100, "url": "lo.mp4"},
                                {"content_type": "video/mp4", "bit_rate": 900, "url": "hi.mp4"}]}]}}
    (c,) = x_sources.parse_official(payload)
    assert (c["video_url"], c["author"], c["duration"], c["likes"]) == ("hi.mp4", "bob", 12, 5)


def test_parse_thirdparty():
    payload = {"tweets": [{"id": "9", "url": "u", "text": "t", "likeCount": 3, "retweetCount": 1, "viewCount": 2,
                           "createdAt": "Tue Nov 10 08:00:00 +0000 2026", "author": {"userName": "x", "name": "X"},
                           "extendedEntities": {"media": [{"type": "video", "video_info": {
                               "duration_millis": 5000,
                               "variants": [{"content_type": "video/mp4", "bitrate": 1, "url": "a.mp4"}]}}]}}]}
    (c,) = x_sources.parse_thirdparty(payload)
    assert c["video_url"] == "a.mp4" and c["duration"] == 5 and c["created"] > 1_700_000_000


def test_filter_and_rank():
    cs = [cand(id="1"), cand(id="2", likes=5), cand(id="3", duration=9999), cand(id="4", author="Spam"),
          cand(id="5", created=0), cand(id="6", likes=9000), cand(id="7")]
    cfg = dict(CFG, blocked_accounts=["@spam"])
    out = x_sources.filter_candidates(cs, cfg, seen={"7"})
    assert [c["id"] for c in out] == ["6", "1"]


def test_escape_keeps_hashtags():
    assert linkedin.escape_commentary("A (b) #KI @x_y") == r"A \(b\) #KI \@x\_y"


def patch_tg(monkeypatch, log):
    monkeypatch.setattr(telegram, "edit", lambda *a, **k: log.append(("edit", a[1])))
    monkeypatch.setattr(telegram, "send", lambda *a, **k: log.append(("send", a[0])) or 99)
    monkeypatch.setattr(telegram, "answer_callback", lambda *a, **k: None)


def test_go_posts_once_and_learns(monkeypatch):
    log, posts = [], []
    patch_tg(monkeypatch, log)
    monkeypatch.setattr(linkedin, "download_video", lambda *a: 1)
    monkeypatch.setattr(linkedin, "upload_video", lambda *a: "urn:li:video:1")
    monkeypatch.setattr(linkedin, "create_post", lambda text, *a: posts.append(text) or "urn:li:share:1")
    state = common.load_state()
    state["pending"]["1"] = cand()
    cb = {"id": "c", "data": "go:1"}
    approve.on_callback(CFG, state, cb)
    approve.on_callback(CFG, state, cb)  # zweiter Klick darf nicht erneut posten
    assert len(posts) == 1 and "@a auf X" in posts[0] and "#KI" in posts[0]
    assert state["pending"] == {} and state["feedback"][-1]["verdict"] == "like"
    assert common.load_state()["posted"][0]["urn"] == "urn:li:share:1"


def test_go_failure_keeps_pending(monkeypatch):
    log = []
    patch_tg(monkeypatch, log)
    monkeypatch.setattr(linkedin, "download_video", lambda *a: (_ for _ in ()).throw(RuntimeError("kaputt")))
    state = common.load_state()
    state["pending"]["1"] = cand()
    approve.on_callback(CFG, state, {"id": "c", "data": "go:1"})
    assert "1" in state["pending"] and any("fehlgeschlagen" in t for k, t in log if k == "send")


def test_skip_and_style(monkeypatch):
    log = []
    patch_tg(monkeypatch, log)
    state = common.load_state()
    state["pending"]["1"] = cand()
    approve.on_callback(CFG, state, {"id": "c", "data": "skip:1"})
    approve.on_message(CFG, state, {"text": "/stil keine Emojis", "chat": {"id": 42}})
    assert state["pending"] == {} and state["feedback"][-1]["verdict"] == "dislike"
    assert state["style_notes"] == ["keine Emojis"]


def test_main_ignores_strangers(monkeypatch):
    log = []
    patch_tg(monkeypatch, log)
    monkeypatch.setattr(telegram, "get_updates", lambda off: [
        {"update_id": 5, "message": {"text": "/status", "chat": {"id": 666}}}])
    approve.main()
    assert log == [] and common.load_state()["tg_offset"] == 6


def test_submitted_link_becomes_draft_and_like(monkeypatch):
    log = []
    patch_tg(monkeypatch, log)
    monkeypatch.setattr(telegram, "send_video", lambda *a: None)
    monkeypatch.setattr(x_sources, "fetch_tweet", lambda cfg, tid: cand(id=tid, msg_id=None))
    monkeypatch.setattr(llm, "draft_for", lambda *a: llm.Draft(post_text="Neu", hashtags=["#A"]))
    state = common.load_state()
    approve.on_message(CFG, state, {"text": "https://x.com/bob/status/123?s=20 genau sowas", "chat": {"id": 42}})
    assert state["pending"]["123"]["post_text"] == "Neu" and "123" in state["seen"]
    assert state["feedback"][-1]["verdict"] == "like" and "genau sowas" in state["feedback"][-1]["note"]


def test_feedback_reason(monkeypatch):
    log = []
    patch_tg(monkeypatch, log)
    state = common.load_state()
    state["pending"]["1"] = cand()
    approve.on_callback(CFG, state, {"id": "c", "data": "dislike:1"})
    approve.on_message(CFG, state, {"text": "zu werblich", "chat": {"id": 42},
                                    "reply_to_message": {"message_id": 99}})
    assert state["feedback"][-1]["note"] == "zu werblich"
