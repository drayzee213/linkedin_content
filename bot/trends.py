"""Lauf 1x pro Woche: LinkedIn-Trends recherchieren und in state/trends.md ablegen."""
import time

from . import llm
from .common import TRENDS_FILE, load_config


def main() -> None:
    text = llm.research_trends(load_config())
    if not text:
        raise SystemExit("Keine Trends erhalten, alte Datei bleibt bestehen.")
    TRENDS_FILE.parent.mkdir(exist_ok=True)
    TRENDS_FILE.write_text(f"<!-- Stand: {time.strftime('%Y-%m-%d')} -->\n{text}\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
