"""Read-only public GitHub repository overview via the GitHub API."""

import base64
import binascii
from dataclasses import dataclass
import http.client
import json
import re
import socket
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_README_CHARS = 16000
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}")


@dataclass(frozen=True)
class RepositoryOverview:
    url: str
    description: str
    language: str
    readme: str
    readme_truncated: bool


def parse_repository_url(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url)
        if (parts.scheme.lower() != "https" or parts.netloc.lower() not in
                ("github.com", "www.github.com") or parts.query or parts.fragment):
            raise ValueError
        path = parts.path.strip("/").split("/")
        if len(path) != 2 or not NAME.fullmatch(path[0]) or not REPO.fullmatch(path[1]):
            raise ValueError
        repo = path[1][:-4] if path[1].lower().endswith(".git") else path[1]
        if repo in ("", ".", ".."):
            raise ValueError
        return path[0], repo
    except ValueError as exc:
        raise ValueError(
            "Use a public repository root URL like https://github.com/owner/repository "
            "without credentials, query strings, or file paths."
        ) from exc


def extract_repository_request(text: str) -> tuple[str, str] | None:
    urls = list(URL_PATTERN.finditer(text))
    github_urls = [match for match in urls if "github.com" in match.group().lower()]
    if not github_urls:
        return None
    if len(github_urls) != 1 or len(urls) != 1:
        raise ValueError("Provide one GitHub repository link at a time.")
    match = github_urls[0]
    url = match.group().rstrip(".,!?)")
    owner, repo = parse_repository_url(url)
    question = (text[:match.start()] + " " + text[match.end():]).strip()
    return f"https://github.com/{owner}/{repo}", question or "Summarize this repository."


def _get_json(path: str) -> dict | None:
    connection = http.client.HTTPSConnection("api.github.com", timeout=15)
    try:
        connection.request("GET", path, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Icewolf-local-assistant",
        })
        response = connection.getresponse()
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"GitHub returned HTTP {response.status}; check connectivity or API rate limits."
            )
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("GitHub returned a response that exceeds the size limit.")
        try:
            result = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("GitHub returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise RuntimeError("GitHub returned an unexpected response.")
        return result
    except (OSError, socket.timeout, http.client.HTTPException) as exc:
        raise RuntimeError(f"Could not reach GitHub: {exc}") from exc
    finally:
        connection.close()


def fetch_overview(url: str) -> RepositoryOverview:
    owner, repo = parse_repository_url(url)
    path = f"/repos/{owner}/{repo}"
    metadata = _get_json(path)
    if metadata is None:
        raise RuntimeError("Repository not found or not public. Only public repositories are supported.")
    if metadata.get("private") is not False:
        raise RuntimeError("GitHub did not confirm that this repository is public.")
    readme_data = _get_json(path + "/readme")
    readme = ""
    if readme_data is not None:
        content = readme_data.get("content")
        if readme_data.get("encoding") != "base64" or not isinstance(content, str):
            raise RuntimeError("GitHub did not return readable README content.")
        try:
            readme = base64.b64decode("".join(content.split()), validate=True).decode("utf-8-sig")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise RuntimeError("The README could not be decoded as UTF-8 text.") from exc
    description = metadata.get("description")
    language = metadata.get("language")
    return RepositoryOverview(
        f"https://github.com/{owner}/{repo}",
        description if isinstance(description, str) else "",
        language if isinstance(language, str) else "",
        readme[:MAX_README_CHARS],
        len(readme) > MAX_README_CHARS,
    )
