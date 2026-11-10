"""Konfiguration und persistenter Zustand (state/state.json wird vom Workflow committet)."""
import json
import os
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "state.json"
TRENDS_FILE = ROOT / "state" / "trends.md"

DEFAULT_STATE = {
    "tg_offset": 0,
    "seen": [],         # bereits vorgeschlagene Tweet-IDs
    "pending": {},      # tweet_id -> Vorschlag, der auf Go/Skip wartet
    "feedback": [],     # Trainingsdaten: {verdict, author, text, note}
    "style_notes": [],  # dauerhafte Stil-Hinweise (/stil ... oder Korrekturen)
    "posted": [],
}


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Umgebungsvariable {name} fehlt (GitHub-Secret anlegen).")
    return value


def load_state() -> dict:
    state = json.loads(json.dumps(DEFAULT_STATE))
    if STATE_FILE.exists():
        state.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return state


def save_state(state: dict) -> None:
    state["seen"] = state["seen"][-3000:]
    state["feedback"] = state["feedback"][-200:]
    state["style_notes"] = state["style_notes"][-30:]
    state["posted"] = state["posted"][-500:]
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def add_feedback(state: dict, cand: dict, verdict: str, note: str = "") -> None:
    state["feedback"].append({
        "verdict": verdict,  # "like" | "dislike"
        "author": cand.get("author", ""),
        "text": cand.get("text", "")[:400],
        "note": note,
        "ts": int(time.time()),
    })


def read_trends() -> str:
    return TRENDS_FILE.read_text(encoding="utf-8") if TRENDS_FILE.exists() else ""
