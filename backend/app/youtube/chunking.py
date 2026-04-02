from __future__ import annotations

from typing import Iterable, Any


def _extract_value(entry: Any, key: str, default: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _normalize_entry(entry: Any) -> dict:
    return {
        "text": str(_extract_value(entry, "text", "") or "").strip(),
        "start": float(_extract_value(entry, "start", 0) or 0),
        "duration": float(_extract_value(entry, "duration", 0) or 0),
    }


def _chunk_plain_text(text: str, max_words: int = 450) -> list[dict]:
    words = text.split()
    if not words:
        return []

    chunks: list[dict] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append({"text": chunk_text, "start": 0, "duration": 0})
        start = end
    return chunks


def chunk_transcript(
    transcript_entries: Iterable[dict] | str,
    min_seconds: float = 30,
    max_seconds: float = 60,
) -> list[dict]:
    if isinstance(transcript_entries, str):
        return _chunk_plain_text(transcript_entries)

    entries = [_normalize_entry(entry) for entry in transcript_entries]
    entries = [entry for entry in entries if entry["text"]]
    if not entries:
        return []

    chunks: list[dict] = []
    buffer: list[str] = []
    chunk_start: float | None = None
    chunk_end: float | None = None

    for idx, entry in enumerate(entries):
        start = entry["start"]
        duration = entry["duration"]
        end = start + duration

        if chunk_start is None:
            chunk_start = start
        chunk_end = end
        buffer.append(entry["text"])

        span = (chunk_end - chunk_start) if chunk_end is not None else 0
        next_start = entries[idx + 1]["start"] if idx + 1 < len(entries) else None

        should_flush = span >= max_seconds
        if not should_flush and next_start is not None:
            projected_span = next_start - chunk_start
            if span >= min_seconds and projected_span > max_seconds:
                should_flush = True

        if should_flush:
            chunks.append(
                {
                    "text": " ".join(buffer).strip(),
                    "start": chunk_start,
                    "duration": span,
                }
            )
            buffer = []
            chunk_start = None
            chunk_end = None

    if buffer:
        end_span = (chunk_end - chunk_start) if chunk_end and chunk_start else 0
        chunks.append(
            {
                "text": " ".join(buffer).strip(),
                "start": chunk_start or 0,
                "duration": end_span,
            }
        )

    return chunks
