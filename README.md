# Content-to-LinkedIn Bot (Telegram-Freigabe, GitHub Actions)

Sucht 3x täglich Video-Posts auf X/Twitter, wählt den besten für deine Nische aus, schreibt
einen deutschen LinkedIn-Text dazu und schickt dir beides per Telegram. Erst nach deinem
**Go** wird das Video heruntergeladen, bei LinkedIn hochgeladen und als Beitrag gepostet.

## Ablauf

| Workflow | Wann | Was |
|---|---|---|
| `scout.yml` | 07:40, 11:40, 16:40 MEZ | X durchsuchen → filtern → Claude wählt aus und textet → Telegram |
| `approve.yml` | alle 30 min (06–22 Uhr MEZ) | deine Telegram-Antworten verarbeiten, bei Go auf LinkedIn posten |
| `trends.yml` | montags | Web-Recherche zu LinkedIn-Trends → `state/trends.md`, fließt in jeden Text ein |

Wegen des 30-Minuten-Takts geht ein Post **bis zu 30 Minuten nach deinem Go** raus
(GitHub-Cron ist zudem oft einige Minuten verspätet).

## Bedienung in Telegram

- **✅ Go** – posten · **❌ Verwerfen** – weg damit (zählt als negatives Beispiel)
- **👍 / 👎** – Geschmack trainieren, ohne zu posten oder zu verwerfen
- **Auf einen Vorschlag antworten** (z. B. „kürzer, ohne Frage am Ende“) – Text wird überarbeitet
- `/stil <Hinweis>` – dauerhafte Regel für alle künftigen Texte · `/stil` · `/stil_reset`
- `/status` – offene Vorschläge und Lernstand

Die letzten 👍/👎-Beispiele und alle Stil-Hinweise gehen bei jeder Auswahl an das Sprachmodell.

## Einrichtung

1. **Privates GitHub-Repo** anlegen und diesen Ordner pushen.
2. **Neuen Telegram-Bot** bei @BotFather erstellen (nicht den Token des Job-Bots
   wiederverwenden, zwei Programme können nicht dieselben Updates abholen). Dem Bot einmal
   schreiben; deine Chat-ID ist dieselbe wie beim Job-Bot.
3. **LinkedIn-App** unter <https://www.linkedin.com/developers/apps> anlegen, Produkte
   „Share on LinkedIn“ und „Sign In with LinkedIn using OpenID Connect“ hinzufügen,
   Redirect-URL `http://localhost:8765/callback` eintragen. Dann lokal:
   ```bash
   pip install requests && python scripts/linkedin_auth.py CLIENT_ID CLIENT_SECRET
   ```
   Der Token läuft nach ca. 60 Tagen ab; der Bot meldet das per Telegram, dann erneut ausführen.
4. **X-Zugang**: Bearer-Token der offiziellen X API *oder* Key von twitterapi.io;
   in `config.yaml` mit `x_source` umschalten.
5. **Secrets** im Repo (Settings → Secrets and variables → Actions):

   | Secret | Für |
   |---|---|
   | `ANTHROPIC_API_KEY` | Auswahl, Texte, Trends |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Freigabe |
   | `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN` | Posten |
   | `X_BEARER_TOKEN` *oder* `TWITTERAPI_IO_KEY` | Suche |

6. Unter **Actions** einmal „Trends“ und dann „Scout“ per „Run workflow“ starten.

Nische, Suchbegriffe, Mindest-Likes, Ton und Zeiten stehen in `config.yaml` bzw. den
Cron-Zeilen der Workflows.

## Wichtig zu wissen

- **Urheberrecht:** Der Bot lädt fremde Videos neu hoch. Die Quellenangabe („Video: Name
  (@handle auf X)“) wird automatisch angehängt, ersetzt aber keine Erlaubnis. Dein Go ist
  die Kontrolle: Poste nur Videos, deren Urheber das Weiterverbreiten erlauben (z. B.
  offizielle Firmen-Demos), oder beschränke die Suche über `accounts` auf solche Quellen.
- **Der Text basiert nur auf dem Tweet-Text**, das Modell sieht das Video nicht. Sieh dir
  die Vorschau an, bevor du Go tippst.
- **Actions-Minuten:** ca. 1.200 pro Monat (privates Repo: 2.000 frei, geteilt mit deinem
  Job-Bot). Bei Bedarf den Takt in `approve.yml` strecken.
- **Kosten:** X API (offiziell: pro gelesenem Post, `max_results_per_query` klein halten)
  und Claude API (wenige Cent pro Lauf).

## Tests

```bash
pip install -r requirements.txt pytest && python -m pytest -q
```
