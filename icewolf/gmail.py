"""Explicit, read-only Gmail access using a locally stored OAuth credential."""

import json
import sys
import html
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SERVICE = "Icewolf Gmail"
ACCOUNT = "authorized-account"

@dataclass(frozen=True)
class InboxReport:
    display: str
    speech: str


def _clean(value: str, limit: int) -> str:
    text = " ".join(html.unescape(value).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _credential_store():
    if sys.platform != "win32":
        raise RuntimeError("Gmail credential storage currently requires Windows Credential Manager.")
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def connect(client_file: str) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    path = Path(client_file).expanduser()
    if not path.is_file():
        raise ValueError("Select the downloaded Google OAuth desktop client JSON file.")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    credentials = flow.run_local_server(
        host="127.0.0.1", port=0, timeout_seconds=180,
        authorization_prompt_message="",
        success_message="Gmail authorization complete. You can close this browser tab.",
    )
    if not credentials.has_scopes(SCOPES):
        raise RuntimeError("Google did not grant the requested Gmail read permission.")
    _credential_store().set_password(SERVICE, ACCOUNT, credentials.to_json())


def inbox_report(limit: int = 5) -> InboxReport:
    import httplib2
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    saved = _credential_store().get_password(SERVICE, ACCOUNT)
    if not saved:
        raise RuntimeError("Gmail is not connected. Use Connect Gmail first.")
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(saved), SCOPES)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("Saved Gmail authorization is invalid; reconnect Gmail.") from exc
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _credential_store().set_password(SERVICE, ACCOUNT, credentials.to_json())
    if not credentials.valid or not credentials.has_scopes(SCOPES):
        raise RuntimeError("Gmail authorization is unavailable or expired; reconnect Gmail.")
    if not 1 <= limit <= 20:
        raise ValueError("Gmail report limit must be between 1 and 20.")

    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=15))
    try:
        service = build("gmail", "v1", http=http, cache_discovery=False)
        messages = service.users().messages()
        listing = messages.list(userId="me", labelIds=["INBOX"], maxResults=limit).execute()
        entries = listing.get("messages", [])
        if not entries:
            return InboxReport("Your inbox has no messages.", "Your inbox has no messages.")
        lines = [f"Here are your latest {len(entries)} inbox messages:"]
        spoken = [f"Here are your latest {len(entries)} inbox messages."]
        for index, entry in enumerate(entries, 1):
            message = messages.get(
                userId="me", id=entry["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {h["name"].lower(): h["value"]
                       for h in message.get("payload", {}).get("headers", [])
                       if "name" in h and "value" in h}
            sender = _clean(headers.get("from", "(unknown sender)"), 200)
            subject = _clean(headers.get("subject", "(no subject)"), 200)
            snippet = _clean(message.get("snippet", ""), 300)
            lines.append(f"{index}. From: {sender}. Subject: {subject}. Preview: {snippet}")
            display_name, address = parseaddr(sender)
            spoken_sender = _clean(display_name or address.split("@")[0] or sender, 40)
            spoken.append(f"Number {index} is from {spoken_sender}, about {_clean(subject, 70)}.")
        spoken.append(
            "Would you like to prepare a reply or organize any of these in Gmail? "
            "I can't send or change messages yet."
        )
        return InboxReport("\n".join(lines), " ".join(spoken))
    finally:
        http.close()
