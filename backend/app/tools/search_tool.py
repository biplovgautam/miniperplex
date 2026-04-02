from __future__ import annotations

from typing import Any

from app.tools.custom_tools import tavily_search


class TavilySearchTool:
    async def run(self, query: str) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        return await tavily_search(query)
