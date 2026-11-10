"""Public YouTube video search for explicit user requests."""

import http.client
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlencode

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


@dataclass(frozen=True)
class VideoRequest:
    query: str
    recent: bool = False


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    channel: str

    @property
    def url(self) -> str:
        return "https://www.youtube.com/watch?" + urlencode({"v": self.video_id})


def extract_request(text: str) -> VideoRequest | None:
    text = text.strip().rstrip(".?!")
    text = re.sub(r"^(?:(?:hey\s+)?ice\s*wolf[, ]+)?", "", text, flags=re.I)
    text = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", text, flags=re.I)
    if re.search(r"\b(?:do not|don't|never)\b", text, re.I):
        return None
    match = re.match(r"^(search(?:\s+for)?|find|play|watch|show(?:\s+me)?)\s+(.+)$", text, re.I)
    if not match:
        return None
    verb, query = match.groups()
    if (verb.lower().startswith("search") and not re.search(
        r"\b(?:youtube|videos?|play|watch)\b", query, re.I
    )):
        return None
    if verb.lower() in ("find", "show", "show me", "watch") and not re.search(
        r"\b(?:youtube|videos?)\b", query, re.I
    ):
        return None
    recent = bool(re.search(r"\b(?:recent|recently|latest|newest)\b", query, re.I))
    query = re.sub(
        r"\s+and\s+(?:(?:have (?:him|it) )?(?:play|watch|show)\s+it\b|"
        r"have (?:him|it) (?:pop\s*up|open)\b).*$", "", query, flags=re.I,
    )
    query = re.sub(r"\s+(?:on|in|from)\s+youtube\b", " ", query, flags=re.I)
    query = re.sub(r"\b(?:youtube|videos?|recent|recently|latest|newest)\b", " ", query, flags=re.I)
    query = re.sub(r"^(?:a|an|the|some|about|of)\s+", "", query.strip(), flags=re.I)
    query = re.sub(r"\s+(?:for me|please)$", "", query.strip(), flags=re.I)
    query = " ".join(query.strip(" ,").split())
    return VideoRequest(query, recent)


def _text(value) -> str:
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    return "".join(part.get("text", "") for part in value.get("runs", [])
                   if isinstance(part, dict) and isinstance(part.get("text", ""), str))


def _videos(value):
    if isinstance(value, dict):
        video = value.get("videoRenderer")
        if isinstance(video, dict):
            yield video
        for key, child in value.items():
            if key != "videoRenderer":
                yield from _videos(child)
    elif isinstance(value, list):
        for child in value:
            yield from _videos(child)


def _age_minutes(value: str) -> int | None:
    value = value.strip().lower()
    if value in ("today", "just now", "streamed live"):
        return 0
    if value == "yesterday":
        return 1440
    match = re.search(
        r"\b(\d+)\s*(minutes?|mins?|hours?|hrs?|h|days?|d|weeks?|wks?|w|months?|mos?|years?|yrs?|y)"
        r"\s+ago\b", value
    )
    if not match:
        return None
    number, unit = match.groups()
    factors = {"min": 1, "hour": 60, "hr": 60, "day": 1440,
               "week": 10080, "wk": 10080, "month": 43200, "mo": 43200,
               "year": 525600, "yr": 525600, "h": 60, "d": 1440, "w": 10080, "y": 525600}
    factor = next((amount for prefix, amount in factors.items() if unit.startswith(prefix)), None)
    return int(number) * factor if factor is not None else None


def search_first(request: VideoRequest) -> Video:
    if not request.query or len(request.query) > 500:
        raise ValueError("Tell me what video to search for (up to 500 characters).")
    params = {"search_query": request.query}
    if request.recent:
        params["sp"] = "CAI="
    connection = http.client.HTTPSConnection("www.youtube.com", timeout=15)
    try:
        connection.request("GET", "/results?" + urlencode(params), headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"YouTube search returned HTTP {response.status}. Try again in your browser.")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("YouTube search returned an unexpectedly large page.")
    except (OSError, socket.timeout, http.client.HTTPException) as exc:
        raise RuntimeError("Could not reach YouTube. Check your internet connection and try again.") from exc
    finally:
        connection.close()
    page = body.decode("utf-8", errors="replace")
    match = re.search(r"(?:var\s+ytInitialData\s*=\s*|window\s*\[\s*[\"']ytInitialData[\"']\s*\]\s*=\s*)", page)
    if match is None:
        raise RuntimeError("YouTube did not provide searchable results; open YouTube in your browser and retry.")
    try:
        data, _ = json.JSONDecoder().raw_decode(page, match.end())
    except (ValueError, RecursionError) as exc:
        raise RuntimeError("Could not read YouTube search results; try again in your browser.") from exc
    candidates = []
    try:
        for item in _videos(data):
            video_id = item.get("videoId")
            title = _text(item.get("title"))
            if isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id) and title:
                video = Video(video_id, title, _text(item.get("ownerText")))
                if not request.recent:
                    return video
                age = _age_minutes(_text(item.get("publishedTimeText")))
                if age is not None:
                    candidates.append((age, video))
    except RecursionError as exc:
        raise RuntimeError("YouTube returned an unexpected search page; try again in your browser.") from exc
    if candidates:
        return min(candidates, key=lambda candidate: candidate[0])[1]
    if request.recent:
        raise RuntimeError("YouTube did not provide dated video results. Try a search without 'recent'.")
    raise RuntimeError("No matching YouTube videos were found. Try a different search.")
