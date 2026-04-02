from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any

from app.core.config import settings
from app.youtube.chunking import chunk_transcript
from app.youtube.storage import init_db, insert_video, video_exists
from app.youtube.utils import (
    extract_video_id,
    fetch_channel_feed,
    fetch_video_metadata,
    get_channel_ids,
    get_transcript_entries,
    to_timestamp,
)

logger = logging.getLogger(__name__)

_DEFAULT_SLEEP_SECONDS = 600


def _normalize_published_at(value: str | None) -> tuple[str | None, float | None]:
    if not value:
        return None, None
    timestamp = to_timestamp(value)
    return value, timestamp


def ingest_video_entry(entry: dict[str, Any]) -> None:
    init_db()
    video_id = entry.get("video_id") or ""
    if not video_id:
        return

    if video_exists(video_id):
        return

    url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    transcript_entries, transcript_text = get_transcript_entries(url)
    if not transcript_entries:
        logger.warning("No transcript for video %s", video_id)
        return

    published_at, published_at_ts = _normalize_published_at(entry.get("published_at"))
    insert_video(
        video_id=video_id,
        title=entry.get("title") or "",
        channel=entry.get("channel") or "",
        published_at=published_at,
        url=url,
        transcript=transcript_text,
    )

    chunks = chunk_transcript(transcript_entries)
    if not chunks:
        logger.warning("No chunks produced for video %s", video_id)
        return

    from app.youtube import retriever as yt_retriever

    vectorstore = yt_retriever.get_vectorstore()
    if vectorstore is None:
        logger.warning("Vector store not configured; skipping embeddings for %s", video_id)
        return

    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []

    for idx, chunk in enumerate(chunks):
        text = chunk.get("text") or ""
        if not text:
            continue
        ids.append(f"{video_id}_{idx}")
        texts.append(text)
        metadatas.append(
            {
                "video_id": video_id,
                "channel": entry.get("channel") or "",
                "title": entry.get("title") or "",
                "url": url,
                "timestamp": chunk.get("start", 0),
                "published_at": published_at,
                "published_at_ts": published_at_ts,
                "topic": "",
            }
        )

    if texts:
        vectorstore.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        logger.info("Indexed %s chunks for video %s", len(texts), video_id)


def ingest_video_url(video_url: str) -> str | None:
    init_db()
    video_id = extract_video_id(video_url)
    if not video_id:
        return None

    if video_exists(video_id):
        return video_id

    metadata = fetch_video_metadata(video_url)
    entry = {
        "video_id": video_id,
        "title": metadata.get("title", ""),
        "channel": metadata.get("channel", ""),
        "published_at": dt.datetime.utcnow().isoformat(),
        "url": video_url,
    }
    ingest_video_entry(entry)
    return video_id


def run_ingestion_cycle() -> None:
    init_db()
    channel_ids = get_channel_ids()
    if not channel_ids:
        return

    for channel_id in channel_ids:
        try:
            entries = fetch_channel_feed(channel_id)
        except Exception as exc:
            logger.warning("Failed to fetch channel %s: %s", channel_id, exc)
            continue

        for entry in entries:
            try:
                ingest_video_entry(entry)
            except Exception as exc:
                logger.warning("Failed to ingest %s: %s", entry.get("video_id"), exc)


def _worker_loop() -> None:
    sleep_seconds = settings.youtube_ingestion_interval
    if sleep_seconds <= 0:
        sleep_seconds = _DEFAULT_SLEEP_SECONDS

    logger.info("YouTube ingestion worker started (interval=%ss)", sleep_seconds)
    while True:
        try:
            run_ingestion_cycle()
        except Exception as exc:
            logger.warning("Ingestion cycle failed: %s", exc)
        time.sleep(sleep_seconds)


def start_ingestion_worker() -> None:
    if not settings.youtube_channel_ids:
        logger.info("No YouTube channels configured; ingestion worker disabled")
        return
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
