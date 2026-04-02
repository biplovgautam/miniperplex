from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


_ROUTER_PROMPT = """You are an intent router for a financial analysis assistant.
Classify the user's query into exactly one of these labels:
- metals
- crypto
- equities
Return ONLY the lowercase label and nothing else.
"""
_ALLOWED_LABELS = {"metals", "crypto", "equities"}


class RouterAgent:
    def __init__(self, llm: Any):
        self.llm = llm

    async def route(self, query: str) -> str:
        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=_ROUTER_PROMPT),
                    HumanMessage(content=query),
                ],
                max_tokens=3,
            )
        except Exception:
            return "metals"

        label = (response.content or "").strip().lower()
        label = label.replace(".", "").replace(",", "")
        label = label.split()[0] if label else ""
        if label not in _ALLOWED_LABELS:
            return "metals"
        return label
