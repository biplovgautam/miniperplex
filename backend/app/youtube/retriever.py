from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import settings
from app.youtube.ingestion import ingest_video_url
from app.youtube.utils import find_youtube_urls

try:
    from pinecone import Pinecone
except ImportError:  # pragma: no cover
    Pinecone = None

try:
    from langchain_pinecone import PineconeVectorStore
except ImportError:  # pragma: no cover
    PineconeVectorStore = None

logger = logging.getLogger(__name__)

_VECTORSTORE: PineconeVectorStore | None = None


class PineconeInferenceEmbeddings(Embeddings):
    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        response = self._client.inference.embed(
            model=self._model,
            inputs=texts,
            parameters={"input_type": input_type},
        )

        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data")
        if data is None:
            data = response

        vectors: list[list[float]] = []
        for item in data:
            if isinstance(item, dict):
                values = item.get("values") or item.get("embedding") or item.get("vector")
            else:
                values = getattr(item, "values", None) or getattr(item, "embedding", None)
            if values is None:
                raise ValueError("Pinecone inference returned unexpected embedding format")
            vectors.append(list(values))

        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, input_type="passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], input_type="query")[0]


def get_vectorstore() -> PineconeVectorStore | None:
    global _VECTORSTORE
    if _VECTORSTORE is not None:
        return _VECTORSTORE

    if Pinecone is None or PineconeVectorStore is None:
        logger.warning("Pinecone dependencies not installed")
        return None

    if not settings.pinecone_api_key or not settings.pinecone_index:
        logger.warning("Pinecone configuration missing")
        return None

    client = Pinecone(api_key=settings.pinecone_api_key)
    index = client.Index(settings.pinecone_index)
    embeddings = PineconeInferenceEmbeddings(
        client=client,
        model=settings.pinecone_embedding_model,
    )
    _VECTORSTORE = PineconeVectorStore(
        index=index,
        embedding=embeddings,
        text_key="text",
        namespace=settings.pinecone_namespace,
    )
    return _VECTORSTORE


def check_pinecone_connection() -> bool:
    if Pinecone is None:
        logger.warning("Pinecone client not installed; skipping check.")
        return False

    if not settings.pinecone_api_key or not settings.pinecone_index:
        logger.info("Pinecone not configured; skipping check.")
        return False

    try:
        client = Pinecone(api_key=settings.pinecone_api_key)
        index = client.Index(settings.pinecone_index)
        index.describe_index_stats()
        logger.info("Pinecone connection OK (index=%s).", settings.pinecone_index)
        return True
    except Exception as exc:
        logger.warning("Pinecone connection failed: %s", exc)
        return False


def _build_filter(filters: dict[str, Any]) -> dict[str, Any]:
    pinecone_filter: dict[str, Any] = {}

    channels = filters.get("channels") or filters.get("channel")
    if isinstance(channels, list) and channels:
        pinecone_filter["channel"] = {"$in": channels}

    video_ids = filters.get("video_ids")
    if isinstance(video_ids, list) and video_ids:
        pinecone_filter["video_id"] = {"$in": video_ids}

    published_after = filters.get("published_after")
    published_before = filters.get("published_before")
    if published_after or published_before:
        range_filter: dict[str, Any] = {}
        if published_after:
            range_filter["$gte"] = _to_epoch(published_after)
        if published_before:
            range_filter["$lte"] = _to_epoch(published_before)
        pinecone_filter["published_at_ts"] = range_filter

    return pinecone_filter


def _to_epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _format_context(documents: list[Document]) -> str:
    lines: list[str] = []
    for index, doc in enumerate(documents, start=1):
        meta = doc.metadata
        channel = meta.get("channel") or ""
        published_at = meta.get("published_at") or ""
        timestamp = meta.get("timestamp")
        time_label = f"@{int(timestamp)}s" if isinstance(timestamp, (int, float)) else ""
        header = " ".join(part for part in [channel, published_at, time_label] if part)
        header_text = f" ({header})" if header else ""
        lines.append(f"[{index}] {doc.page_content}{header_text}")
    return "\n".join(lines)


def _documents_to_sources(documents: list[Document]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, doc in enumerate(documents, start=1):
        meta = doc.metadata
        video_id = meta.get("video_id") or ""
        url = meta.get("url") or (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        )
        title = meta.get("title") or f"YouTube clip {video_id or index}"
        sources.append(
            {
                "index": index,
                "title": title,
                "url": url,
                "site": "youtube.com",
                "snippet": (doc.page_content or "")[:200],
                "favicon": "",
            }
        )
    return sources


def retrieve_youtube_context_with_sources(
    query: str, filters: dict[str, Any] | None = None
) -> tuple[str, list[dict[str, Any]]]:
    vectorstore = get_vectorstore()
    if vectorstore is None:
        return "", []

    filters = filters or {}

    urls = find_youtube_urls(query)
    if urls:
        video_ids: list[str] = []
        for url in urls:
            video_id = ingest_video_url(url)
            if video_id:
                video_ids.append(video_id)
        if video_ids:
            filters["video_ids"] = list(set(filters.get("video_ids", []) + video_ids))

    pinecone_filter = _build_filter(filters)
    k = int(filters.get("k", settings.youtube_retrieval_k))

    try:
        documents = vectorstore.similarity_search(query, k=k, filter=pinecone_filter)
    except Exception as exc:
        logger.warning("YouTube retrieval failed: %s", exc)
        return "", []

    if not documents:
        return "", []

    return _format_context(documents), _documents_to_sources(documents)


def retrieve_youtube_context(query: str, filters: dict[str, Any] | None = None) -> str:
    context, _ = retrieve_youtube_context_with_sources(query, filters)
    return context
