"""The person's Google connection: OAuth, Drive, Sheets, Gmail drafts (decisions 0008, 0012).

Plain HTTPS calls to Google's REST APIs through one client, so tests can swap the transport.
Nothing here sends mail: the only Gmail call creates a draft.
"""

import base64
import json
import logging
import threading
import time
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx

from app.config import get_settings

log = logging.getLogger("app.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
GMAIL_DRAFTS = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"

SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.file",
)
FOLDER = "application/vnd.google-apps.folder"
SPREADSHEET = "application/vnd.google-apps.spreadsheet"


class GoogleError(Exception):
    """`revoked` is set when the person withdrew access (or the token expired for good)."""

    def __init__(self, message: str, revoked: bool = False):
        super().__init__(message)
        self.revoked = revoked


def redirect_uri() -> str:
    return get_settings().app_base_url.rstrip("/") + "/google/callback"


def configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


class Google:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=60)

    # --- OAuth ---------------------------------------------------------------------------------

    def auth_url(self, state: str) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": get_settings().google_client_id, "redirect_uri": redirect_uri(),
            "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
            "prompt": "consent", "include_granted_scopes": "true", "state": state,
        })

    def exchange(self, code: str) -> dict:
        s = get_settings()
        r = self.http.post(TOKEN_URL, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
        })
        if r.status_code != 200:
            raise GoogleError(f"token exchange: {r.status_code}")
        return r.json()

    def access_token(self, refresh_token: str) -> str:
        key = refresh_token[-16:]
        with _token_lock:
            cached = _token_cache.get(key)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
        s = get_settings()
        r = self.http.post(TOKEN_URL, data={
            "refresh_token": refresh_token, "client_id": s.google_client_id,
            "client_secret": s.google_client_secret, "grant_type": "refresh_token",
        })
        if r.status_code != 200:
            revoked = r.status_code in (400, 401) and "invalid_grant" in r.text
            raise GoogleError(f"token refresh: {r.status_code}", revoked=revoked)
        body = r.json()
        with _token_lock:
            _token_cache[key] = (body["access_token"], time.time() + int(body.get("expires_in", 0)))
        return body["access_token"]

    def revoke(self, token: str) -> None:
        try:
            self.http.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            log.warning("Google revoke failed")

    # --- helpers -------------------------------------------------------------------------------

    def _call(self, method: str, url: str, token: str, headers: dict | None = None,
              **kw) -> dict:
        r = self.http.request(method, url,
                              headers={"Authorization": f"Bearer {token}", **(headers or {})}, **kw)
        if r.status_code >= 400:
            raise GoogleError(f"{method} {url.split('?')[0].rsplit('/', 2)[-2:]}: "
                              f"{r.status_code}", revoked=r.status_code == 401)
        return r.json() if r.content else {}

    # --- Drive ---------------------------------------------------------------------------------

    def exists(self, token: str, file_id: str | None) -> bool:
        if not file_id:
            return False
        try:
            meta = self._call("GET", f"{DRIVE_FILES}/{file_id}", token,
                              params={"fields": "id,trashed"})
        except GoogleError as exc:
            if exc.revoked:
                raise
            return False
        return not meta.get("trashed")

    def create_file(self, token: str, name: str, mime: str, parent: str | None = None) -> str:
        body: dict = {"name": name, "mimeType": mime}
        if parent:
            body["parents"] = [parent]
        return self._call("POST", DRIVE_FILES, token, json=body, params={"fields": "id"})["id"]

    def children(self, token: str, folder_id: str) -> dict[str, str]:
        q = f"'{folder_id}' in parents and trashed = false"
        out = self._call("GET", DRIVE_FILES, token,
                         params={"q": q, "fields": "files(id,name)", "pageSize": 200})
        return {f["name"]: f["id"] for f in out.get("files", [])}

    def upload(self, token: str, folder_id: str, name: str, mime: str, data: bytes,
               file_id: str | None = None) -> str:
        boundary = "jsk-boundary-7f3a9c"
        meta = {"name": name} if file_id else {"name": name, "parents": [folder_id]}
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--".encode()
        url = f"{DRIVE_UPLOAD}/{file_id}" if file_id else DRIVE_UPLOAD
        return self._call("PATCH" if file_id else "POST", url, token, content=body,
                          params={"uploadType": "multipart", "fields": "id"},
                          headers={"Content-Type": f"multipart/related; boundary={boundary}"}
                          )["id"]

    # --- Sheets --------------------------------------------------------------------------------

    def write_sheet(self, token: str, sheet_id: str, rows: list[list]) -> None:
        self._call("POST", f"{SHEETS}/{sheet_id}/values/A1:Z100000:clear", token, json={})
        self._call("PUT", f"{SHEETS}/{sheet_id}/values/A1", token,
                   params={"valueInputOption": "RAW"}, json={"values": rows})

    # --- Gmail ---------------------------------------------------------------------------------

    def create_draft(self, token: str, message: EmailMessage) -> dict:
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return self._call("POST", GMAIL_DRAFTS, token, json={"message": {"raw": raw}})


# Tests replace this to talk to a mocked Google.
client_factory = Google


def get_google() -> Google:
    return client_factory()


def email_from_id_token(id_token: str | None) -> str:
    """The id_token came straight from Google's token endpoint over TLS; only its email is used."""
    if not id_token or id_token.count(".") != 2:
        return ""
    payload = id_token.split(".")[1]
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, json.JSONDecodeError):
        return ""
    return str(data.get("email", ""))[:320]
