"""Auswahl + deutsche LinkedIn-Texte mit Claude. Lernt aus Feedback und Stil-Hinweisen."""
import json

import anthropic
from pydantic import BaseModel

from .common import read_trends


class Pick(BaseModel):
    tweet_id: str
    reason: str      # ein Satz: warum passt das zu Nische und Geschmack?
    post_text: str   # fertiger deutscher LinkedIn-Text ohne Hashtags
    hashtags: list[str]


class Selection(BaseModel):
    picks: list[Pick]


class Draft(BaseModel):
    post_text: str
    hashtags: list[str]


RULES = """Du schreibst deutsche LinkedIn-Posts für eine Person, die Videos von X/Twitter \
kuratiert und für ihr deutschsprachiges Netzwerk einordnet.

Nische: {niche}
Ton: {tone}

Regeln für Reichweite auf LinkedIn:
- Die erste Zeile ist der Hook (max. ca. 120 Zeichen): Sie muss allein stehen können, \
weil LinkedIn danach "…mehr anzeigen" abschneidet. Kein Clickbait.
- Kurze Absätze mit Leerzeilen, insgesamt 500 bis 1100 Zeichen.
- Das Video läuft im Post mit: beschreibe, was man darin sieht, und ordne es ein.
- Ende mit einer konkreten Frage, die Fachleute gern beantworten.
- Keine Links im Text. 3 bis 5 Hashtags getrennt im Feld hashtags (mit #), \
Mischung aus breit und spezifisch. Bevorzugte Basis: {hashtags}.
- Fachbegriffe, Produkt- und Firmennamen bleiben im Original.

Regeln für Korrektheit:
- Du kennst nur den Tweet-Text, nicht das Video. Behaupte nichts, was nicht im Tweet steht; \
keine erfundenen Zahlen, Zitate oder Features.
- Das Video stammt nicht von der postenden Person. Schreibe nie so, als hätte sie es \
selbst erstellt. Die Quellenangabe wird automatisch angehängt, schreibe sie nicht selbst.
- Sinngemäß übertragen und einordnen, nicht wörtlich übersetzen.
{extras}"""


def _extras(state: dict) -> str:
    parts = []
    trends = read_trends().strip()
    if trends:
        parts.append("Aktuelle LinkedIn-Trends (wöchentlich recherchiert):\n" + trends)
    if state["style_notes"]:
        parts.append("Dauerhafte Stil-Hinweise der Person (haben Vorrang):\n- "
                     + "\n- ".join(state["style_notes"]))
    likes = [f for f in state["feedback"] if f["verdict"] == "like"][-12:]
    dislikes = [f for f in state["feedback"] if f["verdict"] == "dislike"][-12:]

    def fmt(items):
        return "\n".join(
            f"- @{f['author']}: {f['text'][:220]!r}" + (f" (Anmerkung: {f['note']})" if f.get("note") else "")
            for f in items)
    if likes:
        parts.append("Diese Tweets fand die Person GUT (mehr davon):\n" + fmt(likes))
    if dislikes:
        parts.append("Diese Tweets fand die Person SCHLECHT (so etwas nicht vorschlagen):\n" + fmt(dislikes))
    return ("\n" + "\n\n".join(parts)) if parts else ""


def _system(cfg: dict, state: dict) -> str:
    return RULES.format(niche=cfg["niche"], tone=cfg["tone"],
                        hashtags=" ".join(cfg["hashtags_base"]), extras=_extras(state))


def _parse(cfg: dict, system: str, user: str, schema):
    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=cfg["model"],
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Sprachmodell lieferte kein Ergebnis (stop_reason={resp.stop_reason}).")
    return resp.parsed_output


def select_and_draft(cfg: dict, state: dict, cands: list[dict]) -> list[Pick]:
    n = cfg["posts_per_run"]
    listing = json.dumps([
        {"tweet_id": c["id"], "author": c["author"], "text": c["text"], "likes": c["likes"],
         "reposts": c["reposts"], "views": c["views"], "video_seconds": round(c["duration"])}
        for c in cands], ensure_ascii=False, indent=1)
    user = (f"Hier sind {len(cands)} Video-Tweets. Wähle die {n} besten für die Nische und den "
            f"Geschmack der Person aus (höchstens {n}; lieber weniger als etwas Unpassendes, "
            f"Werbung, Engagement-Bait, Krypto-Shilling oder Politik) und schreibe zu jedem "
            f"den LinkedIn-Post.\n\n{listing}")
    valid = {c["id"] for c in cands}
    picks = _parse(cfg, _system(cfg, state), user, Selection).picks
    return [p for p in picks if p.tweet_id in valid][:n]


def revise(cfg: dict, state: dict, cand: dict, instruction: str) -> Draft:
    user = (f"Original-Tweet von @{cand['author']}:\n{cand['text']}\n\n"
            f"Bisheriger Entwurf:\n{cand['post_text']}\n\nHashtags: {' '.join(cand['hashtags'])}\n\n"
            f"Änderungswunsch der Person:\n{instruction}\n\nÜberarbeite den Post entsprechend.")
    return _parse(cfg, _system(cfg, state), user, Draft)


def research_trends(cfg: dict) -> str:
    """Wöchentliche Web-Recherche: was funktioniert gerade auf LinkedIn in der Nische?"""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": (
        f"Recherchiere im Web den aktuellen Stand (letzte 4 Wochen) zu: (1) Was bevorzugt der "
        f"LinkedIn-Algorithmus derzeit bei Video-Posts (Länge, Format, Hook, Posting-Zeiten im "
        f"DACH-Raum, Hashtags)? (2) Welche Themen und Hashtags sind in der Nische "
        f"'{cfg['niche']}' auf LinkedIn im deutschsprachigen Raum gerade gefragt?\n\n"
        f"Antworte NUR mit einer kompakten deutschen Stichpunktliste (max. 12 Punkte), die ein "
        f"Texter direkt als Leitfaden nutzen kann. Nur Belegtes, keine Vermutungen.")}]
    for _ in range(6):
        resp = client.messages.create(
            model=cfg["model"], max_tokens=16000, messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        )
        if resp.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"Trend-Recherche unvollständig (stop_reason={resp.stop_reason}).")
    text_blocks = [b.text for b in resp.content if b.type == "text"]
    return "".join(text_blocks[-1:]).strip() if text_blocks else ""
