"""Einmalig lokal ausführen: erzeugt LINKEDIN_ACCESS_TOKEN und LINKEDIN_PERSON_URN.

Voraussetzung: LinkedIn-App (https://www.linkedin.com/developers/apps) mit den Produkten
"Share on LinkedIn" und "Sign In with LinkedIn using OpenID Connect" sowie der
Redirect-URL http://localhost:8765/callback

Aufruf:  python scripts/linkedin_auth.py CLIENT_ID CLIENT_SECRET
Der Token gilt ca. 60 Tage, danach erneut ausführen.
"""
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

REDIRECT = "http://localhost:8765/callback"
result = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Fertig. Du kannst dieses Fenster schließen.".encode())

    def log_message(self, *args):
        pass


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    client_id, client_secret = sys.argv[1:]
    state = secrets.token_urlsafe(16)
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "state": state, "scope": "openid profile w_member_social"})
    print("Öffne im Browser:\n" + url)
    webbrowser.open(url)
    HTTPServer(("localhost", 8765), Handler).handle_request()
    if result.get("state") != state or "code" not in result:
        raise SystemExit(f"Autorisierung fehlgeschlagen: {result}")
    tok = requests.post("https://www.linkedin.com/oauth/v2/accessToken", timeout=30, data={
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
        "client_id": client_id, "client_secret": client_secret})
    tok.raise_for_status()
    token = tok.json()
    me = requests.get("https://api.linkedin.com/v2/userinfo", timeout=30,
                      headers={"Authorization": f"Bearer {token['access_token']}"})
    me.raise_for_status()
    print("\nAls GitHub-Secrets eintragen:")
    print("LINKEDIN_ACCESS_TOKEN =", token["access_token"])
    print("LINKEDIN_PERSON_URN   =", f"urn:li:person:{me.json()['sub']}")
    print(f"\nGültig für ca. {token.get('expires_in', 0) // 86400} Tage.")


if __name__ == "__main__":
    main()
