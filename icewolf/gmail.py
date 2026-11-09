"""Gmail authorization and inbox reports using locally stored OAuth credentials."""

import json
import sys
import html
import logging
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
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


def _has_required_scopes(credentials) -> bool:
    granted = credentials.granted_scopes
    if isinstance(granted, str):
        granted = granted.split()
    return credentials.has_scopes(SCOPES) and (
        granted is None or set(SCOPES).issubset(granted)
    )


def _account_address(credentials) -> str:
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=15))
    try:
        profile = build("gmail", "v1", http=http, cache_discovery=False).users().getProfile(
            userId="me"
        ).execute()
        address = profile.get("emailAddress")
        if not isinstance(address, str) or not address:
            raise RuntimeError("Could not verify the Gmail account for the saved credential.")
        return address.casefold()
    except HttpError as exc:
        raise RuntimeError(
            "Could not verify the Gmail account. The existing connection was preserved; "
            "try Connect or reconnect Gmail again."
        ) from exc
    finally:
        http.close()


def connect(client_file: str) -> None:
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2 import OAuth2Error
    from requests.exceptions import RequestException

    path = Path(client_file).expanduser()
    if not path.is_file():
        raise ValueError("Select the downloaded Google OAuth desktop client JSON file.")
    store = _credential_store()
    saved = store.get_password(SERVICE, ACCOUNT)
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    callback_logger = logging.getLogger("google_auth_oauthlib.flow")
    previous_level = callback_logger.level
    callback_logger.setLevel(logging.WARNING)
    try:
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=180, prompt="consent",
            authorization_prompt_message="",
            success_message="Authorization received. Return to Icewolf to see the result.",
        )
    except (OAuth2Error, GoogleAuthError, RequestException, Warning, OSError) as exc:
        raise RuntimeError("Gmail authorization failed. The existing connection was preserved.") from exc
    finally:
        callback_logger.setLevel(previous_level)
    if not _has_required_scopes(credentials):
        raise RuntimeError(
            "Google did not grant Gmail modify access. Use Connect or reconnect Gmail and approve it."
        )
    if not credentials.refresh_token:
        if not saved:
            raise RuntimeError(
                "Google did not provide a refresh token. Use Connect or reconnect Gmail and try again."
            )
        try:
            old_info = json.loads(saved)
            old = Credentials.from_authorized_user_info(old_info)
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "The saved Gmail credential could not be reused. It was preserved; reconnect Gmail."
            ) from exc
        if (not old.refresh_token or old.client_id != credentials.client_id
                or old.client_secret != credentials.client_secret):
            raise RuntimeError(
                "Google did not provide a refresh token for the new Gmail permission. "
                "The existing connection was preserved; use Connect or reconnect Gmail again."
            )
        try:
            candidate = Credentials.from_authorized_user_info(old_info, scopes=SCOPES)
            candidate.refresh(Request())
            if not candidate.valid or not _has_required_scopes(candidate):
                raise RuntimeError(
                    "The saved Gmail authorization cannot be reused. "
                    "It was preserved; reconnect Gmail."
                )
            if _account_address(candidate) != _account_address(credentials):
                raise RuntimeError(
                    "The selected Gmail account differs from the saved account and Google did not "
                    "provide a new refresh token. The existing connection was preserved; reconnect."
                )
        except GoogleAuthError as exc:
            raise RuntimeError(
                "Could not verify the existing Gmail authorization. "
                "It was preserved; use Connect or reconnect Gmail again."
            ) from exc
        store.set_password(SERVICE, ACCOUNT, candidate.to_json())
        return
    store.set_password(SERVICE, ACCOUNT, credentials.to_json())


def inbox_report(limit: int = 5) -> InboxReport:
    import httplib2
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    saved = _credential_store().get_password(SERVICE, ACCOUNT)
    if not saved:
        raise RuntimeError("Gmail is not connected. Use Connect Gmail first.")
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(saved))
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Saved Gmail authorization is invalid; reconnect Gmail.") from exc
    if not _has_required_scopes(credentials):
        raise RuntimeError(
            "Gmail needs updated permission. Open Configuration and select Connect or reconnect Gmail."
        )
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except GoogleAuthError as exc:
            raise RuntimeError(
                "Gmail authorization could not be refreshed. Open Configuration and select "
                "Connect or reconnect Gmail."
            ) from exc
        if not _has_required_scopes(credentials):
            raise RuntimeError(
                "Gmail permission is insufficient. Open Configuration and select Connect or reconnect Gmail."
            )
        _credential_store().set_password(SERVICE, ACCOUNT, credentials.to_json())
    if not credentials.valid or not _has_required_scopes(credentials):
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
    except HttpError as exc:
        if exc.resp.status in (401, 403):
            raise RuntimeError(
                "Gmail rejected the request due to authorization or access restrictions. "
                "Check your Google account permissions and use Connect or reconnect Gmail."
            ) from exc
        raise RuntimeError(f"Gmail request failed (HTTP {exc.resp.status}).") from exc
    finally:
        http.close()
