from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from importlib.metadata import PackageNotFoundError, version
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed?url={url}&format=json"

_YT_MODULE = None


def _load_transcriber_module() -> Any | None:
    global _YT_MODULE
    if _YT_MODULE is not None:
        return _YT_MODULE

    module_path = Path(__file__).resolve().parents[1] / "services" / "yt-transcribe.py"
    if not module_path.exists():
        logger.warning("yt-transcribe.py not found at %s", module_path)
        _YT_MODULE = None
        return None

    spec = importlib.util.spec_from_file_location("yt_transcribe", module_path)
    if spec is None or spec.loader is None:
        logger.warning("Unable to load yt-transcribe module spec")
        _YT_MODULE = None
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _YT_MODULE = module
    return module


def extract_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()

    if hostname in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        if parsed_url.path == "/watch":
            return parse_qs(parsed_url.query).get("v", [None])[0]
        if parsed_url.path.startswith("/shorts/"):
            return parsed_url.path.split("/")[2]
        if parsed_url.path.startswith("/embed/"):
            return parsed_url.path.split("/")[2]

    if hostname == "youtu.be":
        return parsed_url.path.strip("/") or None

    return None


def find_youtube_urls(text: str) -> list[str]:
    pattern = r"https?://(?:www\\.)?(?:youtube\\.com|youtu\\.be)/[^\s]+"
    return re.findall(pattern, text)


def fetch_channel_feed(channel_id: str) -> list[dict[str, Any]]:
    url = YOUTUBE_FEED_URL.format(channel_id=channel_id)
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    import xml.etree.ElementTree as ET

    root = ET.fromstring(response.text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    entries: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
        if not video_id:
            continue
        title = entry.findtext("atom:title", default="", namespaces=ns)
        published = entry.findtext("atom:published", default="", namespaces=ns)
        channel_title = entry.findtext("atom:author/atom:name", default="", namespaces=ns)
        channel_id_value = entry.findtext("yt:channelId", default=channel_id, namespaces=ns)

        link = entry.find("atom:link", ns)
        url_value = (
            link.attrib.get("href")
            if link is not None
            else f"https://www.youtube.com/watch?v={video_id}"
        )

        entries.append(
            {
                "video_id": video_id,
                "title": title,
                "published_at": published,
                "channel": channel_title,
                "channel_id": channel_id_value,
                "url": url_value,
            }
        )

    return entries


def fetch_video_metadata(video_url: str) -> dict[str, Any]:
    try:
        response = requests.get(
            YOUTUBE_OEMBED_URL.format(url=video_url), timeout=15
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "title": payload.get("title") or "",
            "channel": payload.get("author_name") or "",
        }
    except Exception as exc:
        logger.warning("Failed to fetch oEmbed metadata: %s", exc)
        return {"title": "", "channel": ""}


def _transcribe_with_existing_pipeline(video_url: str) -> str | None:
    module = _load_transcriber_module()
    if module is None:
        return None

    try:
        return module.transcribe_video_audio_with_assemblyai(video_url)
    except Exception as exc:
        logger.warning("AssemblyAI transcription failed: %s", exc)
        return None


def _fetch_youtube_transcript(video_id: str) -> list[dict[str, Any]] | None:
    try:
        api = YouTubeTranscriptApi()
        try:
            api_version = version("youtube-transcript-api")
        except PackageNotFoundError:
            api_version = "0.0.0"

        if api_version.startswith("1") and hasattr(api, "fetch"):
            transcript = api.fetch(video_id)
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript = transcripts.find_manually_created_transcript(["en"]).fetch()
            except Exception:
                transcript = transcripts.find_generated_transcript(["en"]).fetch()

        if not transcript:
            return None
        return transcript
    except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript):
        return None
    except Exception as exc:
        logger.warning("Transcript fetch failed: %s", exc)
        return None


def transcript_entries_to_text(entries: list[dict[str, Any]]) -> str:
    def _extract_value(entry: Any, key: str, default: Any) -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    return " ".join(
        str(_extract_value(entry, "text", "") or "").strip() for entry in entries
    ).strip()


def get_transcript_entries(video_url: str) -> tuple[list[dict[str, Any]], str]:
    video_id = extract_video_id(video_url)
    if not video_id:
        return [], ""

    transcript = _fetch_youtube_transcript(video_id)
    if transcript:
        return transcript, transcript_entries_to_text(transcript)

    assembly_text = _transcribe_with_existing_pipeline(video_url)
    if not assembly_text:
        return [], ""

    fallback_entry = {"text": assembly_text, "start": 0, "duration": 0}
    return [fallback_entry], assembly_text


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_timestamp(value: str | None) -> float | None:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return None
    return parsed.timestamp()


def get_channel_ids() -> list[str]:
    return settings.youtube_channel_ids
