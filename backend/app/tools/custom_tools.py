from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from langchain_core.tools import tool

from app.core.config import settings


async def tavily_search(query: str) -> tuple[list[dict], str, dict]:
    if not settings.tavily_api_key:
        raise HTTPException(
            status_code=503,
            detail="TAVILY_API_KEY is not set. Configure it to enable web search.",
        )

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": 5,
        "search_depth": "basic",
        "include_answer": False,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(settings.tavily_url, json=payload)
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not results:
        return [], "No results found.", {"query": query, "sources": []}

    summary_lines: list[str] = []
    sources_payload: list[dict] = []
    for index, result in enumerate(results, start=1):
        title = result.get("title") or "Untitled"
        url = result.get("url") or ""
        favicon = ""
        if url:
            favicon = f"https://www.google.com/s2/favicons?domain={urlparse(url).hostname or ''}&sz=64"
        snippet = result.get("content") or result.get("snippet") or ""
        summary_lines.append(f"[{index}] {title} - {snippet}")

        if url:
            hostname = urlparse(url).hostname or ""
            sources_payload.append(
                {
                    "index": index,
                    "title": title,
                    "url": url,
                    "site": hostname.replace("www.", "") if hostname else "",
                    "snippet": snippet,
                    "favicon": favicon,
                }
            )

    tool_text = "Search results:\n" + "\n".join(summary_lines)
    return results, tool_text, {"query": query, "sources": sources_payload}


@tool
async def web_search(query: str) -> str:
    """Search the web via Tavily and return numbered sources."""
    _, tool_text, _ = await tavily_search(query)
    return tool_text
