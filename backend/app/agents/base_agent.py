from __future__ import annotations

from typing import Any


class BaseAgent:
    def __init__(self, tools: dict[str, Any], llm: Any):
        self.tools = tools
        self.llm = llm

    async def run(self, query: str, history: list):
        raise NotImplementedError
