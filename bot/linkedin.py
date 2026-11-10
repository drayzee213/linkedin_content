"""LinkedIn: Video hochladen (Videos API) und als Beitrag veröffentlichen (Posts API)."""
import os
import re
import time
from urllib.parse import quote

import requests

API = "https://api.linkedin.com/rest"
TIMEOUT = 120


class AuthError(RuntimeError):
    pass


def _headers(version: str) -> dict:
    return {
        "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
        "LinkedIn-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _check(r: requests.Response) -> requests.Response:
    if r.status_code == 401:
        raise AuthError("LinkedIn-Token abgelaufen oder ungültig. Neu erzeugen mit "
                        "scripts/linkedin_auth.py und Secret LINKEDIN_ACCESS_TOKEN aktualisieren.")
    if r.status_code >= 400:
        raise RuntimeError(f"LinkedIn {r.status_code}: {r.text[:400]}")
    return r


def escape_commentary(text: str) -> str:
    """LinkedIns 'little text format': reservierte Zeichen müssen escaped werden.
    '#' bleibt unangetastet, damit Hashtags funktionieren."""
    return re.sub(r"([\\|{}@\[\]()<>*_~])", r"\\\1", text)


def download_video(url: str, dest: str, max_mb: int) -> int:
    size = 0
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > max_mb * (1 << 20):
                    raise RuntimeError(f"Video größer als {max_mb} MB.")
                f.write(chunk)
    return size


def upload_video(path: str, version: str) -> str:
    owner = os.environ["LINKEDIN_PERSON_URN"]
    size = os.path.getsize(path)
    init = _check(requests.post(
        f"{API}/videos?action=initializeUpload", headers=_headers(version), timeout=TIMEOUT,
        json={"initializeUploadRequest": {"owner": owner, "fileSizeBytes": size,
                                          "uploadCaptions": False, "uploadThumbnail": False}},
    )).json()["value"]
    etags = []
    with open(path, "rb") as f:
        for part in init["uploadInstructions"]:
            f.seek(part["firstByte"])
            data = f.read(part["lastByte"] - part["firstByte"] + 1)
            r = requests.put(part["uploadUrl"], data=data, timeout=600,
                             headers={"Content-Type": "application/octet-stream"})
            r.raise_for_status()
            etags.append(r.headers["ETag"].strip('"'))
    _check(requests.post(
        f"{API}/videos?action=finalizeUpload", headers=_headers(version), timeout=TIMEOUT,
        json={"finalizeUploadRequest": {"video": init["video"],
                                        "uploadToken": init.get("uploadToken", ""),
                                        "uploadedPartIds": etags}},
    ))
    urn = init["video"]
    for _ in range(60):  # bis zu 5 Minuten auf die Verarbeitung warten
        status = _check(requests.get(f"{API}/videos/{quote(urn, safe='')}",
                                     headers=_headers(version), timeout=TIMEOUT)).json().get("status")
        if status == "AVAILABLE":
            return urn
        if status == "PROCESSING_FAILED":
            raise RuntimeError("LinkedIn konnte das Video nicht verarbeiten.")
        time.sleep(5)
    raise RuntimeError("LinkedIn-Videoverarbeitung dauert zu lange.")


def create_post(text: str, video_urn: str, title: str, version: str) -> str:
    r = _check(requests.post(f"{API}/posts", headers=_headers(version), timeout=TIMEOUT, json={
        "author": os.environ["LINKEDIN_PERSON_URN"],
        "commentary": escape_commentary(text)[:3000],
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "content": {"media": {"title": title[:100], "id": video_urn}},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }))
    return r.headers.get("x-restli-id", "")
