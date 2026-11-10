"""Lauf alle paar Minuten: Telegram-Antworten abholen (Go, Verwerfen, Feedback, Korrekturen)."""
import html
import os
import re
import tempfile
import time

from . import linkedin, llm, telegram, x_sources
from .common import add_feedback, load_config, load_state, save_state

TWEET_URL = re.compile(r"(?:x|twitter)\.com/\w+/status(?:es)?/(\d+)")

HELP = ("<b>Befehle</b>\n"
        "Link zu einem X-Post schicken – ich baue daraus einen Vorschlag und merke mir die Art\n"
        "/status – offene Vorschläge und Lernstand\n"
        "/stil &lt;Hinweis&gt; – dauerhafter Stil-Hinweis, z. B. <code>/stil keine Emojis</code>\n"
        "/stil – Hinweise anzeigen · /stil_reset – alle löschen\n"
        "Antwort auf einen Vorschlag = Text überarbeiten lassen.")


def full_text(cfg: dict, cand: dict) -> str:
    credit = f"🎥 Video: {cand['author_name'] or cand['author']} (@{cand['author']} auf X)"
    if cfg.get("source_link_in_post"):
        credit += f"\n{cand['url']}"
    return f"{cand['post_text']}\n\n{credit}\n\n{' '.join(cand['hashtags'])}"


def publish(cfg: dict, state: dict, cand: dict) -> None:
    telegram.edit(cand["msg_id"], "⏳ Wird auf LinkedIn gepostet …")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "video.mp4")
        linkedin.download_video(cand["video_url"], path, cfg["video_max_mb"])
        video_urn = linkedin.upload_video(path, cfg["linkedin_version"])
    title = cand["post_text"].split("\n", 1)[0]
    post_urn = linkedin.create_post(full_text(cfg, cand), video_urn, title, cfg["linkedin_version"])
    # Sofort sichern, damit ein späterer Fehler nie zu einem Doppel-Post führt.
    state["pending"].pop(cand["id"], None)
    state["posted"].append({"id": cand["id"], "urn": post_urn, "ts": int(time.time())})
    add_feedback(state, cand, "like", "wurde gepostet")
    save_state(state)
    link = f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else ""
    try:  # der Post ist draußen; ein Telegram-Fehler darf hier nichts mehr auslösen
        telegram.edit(cand["msg_id"], "✅ Gepostet" + (f': <a href="{link}">ansehen</a>' if link else "")
                      + f"\n\n{html.escape(cand['post_text'])}")
    except Exception as e:
        print(f"Bestätigung konnte nicht gesendet werden: {e}")


def on_callback(cfg: dict, state: dict, cb: dict) -> None:
    action, _, cid = cb.get("data", "").partition(":")
    cand = state["pending"].get(cid)
    if not cand:
        telegram.answer_callback(cb["id"], "Nicht mehr offen.")
        return
    if action == "go":
        telegram.answer_callback(cb["id"], "Wird gepostet …")
        try:
            publish(cfg, state, cand)
        except Exception as e:
            telegram.edit(cand["msg_id"], telegram.draft_text(cand), telegram.draft_buttons(cid))
            telegram.send(f"⚠️ Posten fehlgeschlagen: {html.escape(str(e))}\n"
                          f"Der Vorschlag bleibt offen, du kannst erneut auf Go tippen.",
                          reply_to=cand["msg_id"])
    elif action == "skip":
        add_feedback(state, cand, "dislike", "verworfen")
        state["pending"].pop(cid)
        telegram.answer_callback(cb["id"], "Verworfen.")
        telegram.edit(cand["msg_id"], f"❌ Verworfen · @{html.escape(cand['author'])}")
    elif action in ("like", "dislike"):
        add_feedback(state, cand, action)
        telegram.answer_callback(cb["id"], "Gemerkt 👍" if action == "like" else "Gemerkt 👎")
        ask = telegram.send("Gemerkt: " + ("mehr davon 👍" if action == "like" else "weniger davon 👎")
                            + "\nWenn du magst: Antworte auf diese Nachricht mit dem Grund.",
                            reply_to=cand["msg_id"])
        state["feedback"][-1]["ask_msg"] = ask


def on_link(cfg: dict, state: dict, tweet_id: str, comment: str) -> None:
    """Selbst eingereichter X-Link: Vorschlag bauen und als positives Beispiel merken."""
    if tweet_id in state["pending"]:
        telegram.send("Dazu liegt schon ein offener Vorschlag vor.")
        return
    cand = x_sources.fetch_tweet(cfg, tweet_id)
    if not cand:
        telegram.send("In dem Post finde ich kein Video (oder er ist nicht abrufbar). "
                      "Ich kann nur Video-Posts verarbeiten.")
        return
    add_feedback(state, cand, "like", ("selbst eingereicht" + (": " + comment if comment else "")))
    draft = llm.draft_for(cfg, state, cand)
    cand.update(reason="Von dir eingereicht", post_text=draft.post_text.strip(),
                hashtags=draft.hashtags, sent=int(time.time()))
    telegram.send_video(cand["video_url"],
                        f"🎬 @{html.escape(cand['author'])} · {round(cand['duration'])} s")
    cand["msg_id"] = telegram.send(telegram.draft_text(cand), telegram.draft_buttons(cand["id"]))
    state["pending"][cand["id"]] = cand
    if cand["id"] not in state["seen"]:
        state["seen"].append(cand["id"])


def on_message(cfg: dict, state: dict, msg: dict) -> None:
    text = (msg.get("text") or "").strip()
    if not text:
        return
    reply_id = (msg.get("reply_to_message") or {}).get("message_id")
    cand = next((c for c in state["pending"].values() if c["msg_id"] == reply_id), None)
    fb = next((f for f in state["feedback"] if reply_id and f.get("ask_msg") == reply_id), None)
    link = TWEET_URL.search(text)
    if fb and not text.startswith("/"):
        fb["note"] = text[:300]
        telegram.send("Danke, Grund gemerkt.")
    elif link:
        on_link(cfg, state, link.group(1), re.sub(r"https?://\S+", "", text).strip()[:300])
    elif cand and not text.startswith("/"):
        draft = llm.revise(cfg, state, cand, text)
        cand.update(post_text=draft.post_text.strip(), hashtags=draft.hashtags)
        try:
            telegram.edit(cand["msg_id"], "↪️ Überarbeitet, neue Version siehe unten.")
        except Exception:
            pass
        cand["msg_id"] = telegram.send(telegram.draft_text(cand), telegram.draft_buttons(cand["id"]))
        telegram.send("Soll ich mir das dauerhaft merken? Dann sende:\n"
                      f"<code>/stil {html.escape(text)}</code>")
    elif text.startswith("/stil_reset"):
        state["style_notes"] = []
        telegram.send("Stil-Hinweise gelöscht.")
    elif text.startswith("/stil"):
        note = text[5:].strip()
        if note:
            state["style_notes"].append(note)
            telegram.send("Gemerkt. Gilt ab dem nächsten Vorschlag.")
        else:
            notes = "\n".join(f"• {html.escape(n)}" for n in state["style_notes"]) or "keine"
            telegram.send(f"<b>Stil-Hinweise</b>\n{notes}")
    elif text.startswith("/status"):
        fb = state["feedback"]
        telegram.send(f"Offene Vorschläge: {len(state['pending'])}\n"
                      f"Gepostet: {len(state['posted'])}\n"
                      f"Feedback: {sum(f['verdict'] == 'like' for f in fb)} 👍 / "
                      f"{sum(f['verdict'] == 'dislike' for f in fb)} 👎\n"
                      f"Stil-Hinweise: {len(state['style_notes'])}")
    else:
        telegram.send(HELP)


def main() -> None:
    cfg, state = load_config(), load_state()
    owner = str(telegram.chat_id())
    for upd in telegram.get_updates(state["tg_offset"]):
        # Offset zuerst sichern: ein Update wird nie zweimal verarbeitet.
        state["tg_offset"] = upd["update_id"] + 1
        save_state(state)
        try:
            if "callback_query" in upd:
                cb = upd["callback_query"]
                if str(cb.get("message", {}).get("chat", {}).get("id")) == owner:
                    on_callback(cfg, state, cb)
            elif "message" in upd:
                if str(upd["message"]["chat"]["id"]) == owner:  # Fremde ignorieren
                    on_message(cfg, state, upd["message"])
        except Exception as e:
            print(f"Fehler bei Update {upd['update_id']}: {e}")
            try:
                telegram.send(f"⚠️ Fehler: {html.escape(str(e))}")
            except Exception:
                pass
        save_state(state)


if __name__ == "__main__":
    main()
