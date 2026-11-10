"""Schlanker Telegram-Bot-API-Client (nur was der Bot braucht)."""
import html
import os

import requests

TIMEOUT = 60


def _call(method: str, **params):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=TIMEOUT)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    return data["result"]


def chat_id() -> str:
    return os.environ["TELEGRAM_CHAT_ID"]


def send(text: str, buttons: list | None = None, reply_to: int | None = None) -> int:
    params = {"chat_id": chat_id(), "text": text[:4096], "parse_mode": "HTML",
              "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return _call("sendMessage", **params)["message_id"]


def send_video(video_url: str, caption: str) -> None:
    """Video-Vorschau. Telegram lädt per URL nur bis ca. 20 MB; sonst reicht der Link."""
    try:
        _call("sendVideo", chat_id=chat_id(), video=video_url, caption=caption[:1024],
              parse_mode="HTML", supports_streaming=True)
    except Exception as e:  # zu groß o. Ä.
        print(f"sendVideo fehlgeschlagen ({e}), sende Link.")
        send(caption + f'\n\n<a href="{html.escape(video_url)}">Video ansehen</a>')


def edit(message_id: int, text: str, buttons: list | None = None) -> None:
    params = {"chat_id": chat_id(), "message_id": message_id, "text": text[:4096],
              "parse_mode": "HTML", "disable_web_page_preview": True,
              "reply_markup": {"inline_keyboard": buttons or []}}
    try:
        _call("editMessageText", **params)
    except RuntimeError as e:
        if "not modified" not in str(e):
            raise


def answer_callback(callback_id: str, text: str = "") -> None:
    try:  # schlägt fehl, wenn der Klick älter als ein paar Minuten ist: egal
        _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except RuntimeError:
        pass


def get_updates(offset: int) -> list:
    return _call("getUpdates", offset=offset, timeout=0,
                 allowed_updates=["message", "callback_query"])


def draft_buttons(cid: str) -> list:
    return [
        [{"text": "✅ Go – posten", "callback_data": f"go:{cid}"},
         {"text": "❌ Verwerfen", "callback_data": f"skip:{cid}"}],
        [{"text": "👍 Mehr davon", "callback_data": f"like:{cid}"},
         {"text": "👎 Weniger davon", "callback_data": f"dislike:{cid}"}],
    ]


def draft_text(cand: dict) -> str:
    e = html.escape
    return (f"<b>Vorschlag</b> · @{e(cand['author'])} · ❤ {cand['likes']} · "
            f"<a href=\"{e(cand['url'])}\">Original</a>\n"
            f"<i>{e(cand.get('reason', ''))}</i>\n\n"
            f"{e(cand['post_text'])}\n\n{e(' '.join(cand['hashtags']))}\n\n"
            f"<i>Antworte auf diese Nachricht mit einem Änderungswunsch, um den Text zu überarbeiten.</i>")
