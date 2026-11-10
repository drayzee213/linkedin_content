"""Lauf 2-3x täglich: X durchsuchen, auswählen, übersetzen, per Telegram zur Freigabe schicken."""
import html
import time

from . import llm, telegram, x_sources
from .common import load_config, load_state, save_state


def expire_pending(state: dict, cfg: dict) -> None:
    limit = time.time() - cfg["pending_expire_hours"] * 3600
    for cid in [c for c, p in state["pending"].items() if p["sent"] < limit]:
        cand = state["pending"].pop(cid)
        try:
            telegram.edit(cand["msg_id"], "⌛ Vorschlag verfallen (keine Antwort).")
        except Exception as e:
            print(f"Konnte verfallene Nachricht nicht bearbeiten: {e}")


def main() -> None:
    cfg, state = load_config(), load_state()
    expire_pending(state, cfg)

    found = x_sources.search(cfg)
    cands = x_sources.filter_candidates(found, cfg, set(state["seen"]))
    print(f"{len(found)} Video-Tweets gefunden, {len(cands)} nach Filter.")
    cands = cands[:cfg["llm_candidates"]]
    if not cands:
        save_state(state)
        return

    by_id = {c["id"]: c for c in cands}
    for pick in llm.select_and_draft(cfg, state, cands):
        cand = dict(by_id[pick.tweet_id])
        cand.update(reason=pick.reason, post_text=pick.post_text.strip(),
                    hashtags=pick.hashtags, sent=int(time.time()))
        telegram.send_video(cand["video_url"],
                            f"🎬 @{html.escape(cand['author'])} · {round(cand['duration'])} s")
        cand["msg_id"] = telegram.send(telegram.draft_text(cand), telegram.draft_buttons(cand["id"]))
        state["pending"][cand["id"]] = cand
        state["seen"].append(cand["id"])
        save_state(state)
    save_state(state)


if __name__ == "__main__":
    main()
