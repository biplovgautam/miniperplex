from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import BaseAgent
from app.agents.prompts import REACT_PLANNER_PROMPT, REWRITE_PROMPT, SYSTEM_PROMPT
from app.schemas.chat import ChatTurn
from app.youtube.retriever import retrieve_youtube_context_with_sources

_TOOL_TIMEOUT_SECONDS = 5
_MAX_REACT_STEPS = 2
_MAX_FOLLOW_UP_QUERIES = 2
_MAX_CONTEXT_SOURCES = 12


def _sse_event(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "\n".join([f"data: {line}" for line in lines])
    return f"event: {event}\n{payload}\n\n"


class MetalsAgent(BaseAgent):
    async def _rewrite_query(self, query: str, history: list[ChatTurn]) -> str:
        history_text = "\n".join(
            [f"{turn.role.title()}: {turn.content}" for turn in history[-6:]]
        ).strip()
        prompt_text = (
            f"Conversation so far:\n{history_text}\n\nUser question: {query}"
            if history_text
            else f"User question: {query}"
        )
        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=REWRITE_PROMPT),
                    HumanMessage(content=prompt_text),
                ],
                max_tokens=32,
            )
        except Exception:
            return query

        rewritten = (response.content or "").strip().strip('"')
        return rewritten or query

    def _build_search_query(self, rewritten_query: str) -> str:
        return f"gold silver market analysis {rewritten_query}".strip()

    def _is_smalltalk(self, query: str) -> bool:
        lowered = re.sub(r"[^a-z0-9\\s]", "", query.lower()).strip()
        if not lowered:
            return True
        greetings = {
            "hi",
            "hello",
            "hey",
            "yo",
            "sup",
            "thanks",
            "thank you",
            "thx",
            "ok",
            "okay",
            "good morning",
            "good afternoon",
            "good evening",
        }
        if lowered in greetings:
            return True
        if lowered.startswith("how are you"):
            return True
        if len(lowered.split()) <= 3 and any(
            lowered.startswith(greet) for greet in greetings
        ):
            return True
        return False

    def _is_metals_query(self, query: str) -> bool:
        lowered = query.lower()
        metals_terms = [
            "gold",
            "silver",
            "xau",
            "xag",
            "gld",
            "slv",
            "bullion",
            "precious metal",
            "metals",
        ]
        measurement_terms = [
            "ounce",
            "oz",
            "troy",
            "gram",
            "grams",
            "kilogram",
            "kilograms",
            "kg",
            "ton",
            "tons",
            "tonne",
            "tonnes",
        ]
        return any(term in lowered for term in metals_terms + measurement_terms)

    def _history_mentions_metals(self, history: list[ChatTurn]) -> bool:
        if not history:
            return False
        terms = [
            "gold",
            "silver",
            "xau",
            "xag",
            "gld",
            "slv",
            "bullion",
            "precious metal",
            "metals",
        ]
        for turn in history[-6:]:
            content = (turn.content or "").lower()
            if any(term in content for term in terms):
                return True
        return False

    def _should_search(self, query: str) -> bool:
        if self._is_smalltalk(query):
            return False

        lowered = query.lower()
        fresh_data_markers = [
            "today",
            "current",
            "latest",
            "now",
            "price",
            "spot",
            "quote",
            "market cap",
            "market capitalization",
            "cap",
            "supply",
            "demand",
            "tonnes",
            "ounces",
            "holdings",
            "etf",
            "yield",
            "rates",
            "inflation",
            "news",
            "earnings",
            "forecast",
            "outlook",
            "bull",
            "bear",
        ]
        if any(marker in lowered for marker in fresh_data_markers):
            return True

        finance_keywords = [
            "gold",
            "silver",
            "xau",
            "xag",
            "gld",
            "slv",
            "commodities",
            "macro",
            "equities",
            "crypto",
            "bitcoin",
            "stocks",
            "market",
        ]
        if "?" in query and any(keyword in lowered for keyword in finance_keywords):
            return True

        return False

    def _contains_youtube_url(self, query: str) -> bool:
        return bool(re.search(r"https?://(?:www\\.)?(?:youtube\\.com|youtu\\.be)/", query))

    def _is_gold_total_market_cap_query(self, query: str) -> bool:
        lowered = query.lower()
        has_market_cap = "market cap" in lowered or "market capitalization" in lowered
        mentions_gold = "gold" in lowered or "xau" in lowered
        mentions_total = "total" in lowered or "global" in lowered or "all" in lowered
        return has_market_cap and mentions_gold and mentions_total

    def _is_ambiguous_market_cap_query(self, query: str) -> bool:
        lowered = query.lower()
        if "market cap" not in lowered and "market capitalization" not in lowered:
            return False

        explicit_terms = {
            "gold",
            "silver",
            "xau",
            "xag",
            "gld",
            "slv",
            "gold.com",
            "newmont",
            "barrick",
            "agnico",
            "wheaton",
        }
        if any(term in lowered for term in explicit_terms):
            return False

        if re.search(r"\$[A-Za-z]{1,6}\b", query):
            return False
        if re.search(r"\b[A-Z]{2,6}\b", query):
            return False
        return True

    def _extract_json_object(self, content: str) -> dict[str, Any] | None:
        cleaned = content.strip()
        if not cleaned:
            return None

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None

        try:
            loaded = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

        return loaded if isinstance(loaded, dict) else None

    def _sanitize_follow_up_queries(self, raw_queries: Any) -> list[str]:
        if not isinstance(raw_queries, list):
            return []

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_queries:
            if not isinstance(item, str):
                continue

            normalized = " ".join(item.split()).strip()
            if len(normalized) < 4:
                continue

            key = normalized.lower()
            if key in seen:
                continue

            seen.add(key)
            cleaned.append(normalized)
            if len(cleaned) >= _MAX_FOLLOW_UP_QUERIES:
                break

        return cleaned

    def _extract_sources(self, sources_payload: Any) -> list[dict[str, Any]]:
        if not isinstance(sources_payload, dict):
            return []

        raw_sources = sources_payload.get("sources", [])
        if not isinstance(raw_sources, list):
            return []

        normalized_sources: list[dict[str, Any]] = []
        for source in raw_sources:
            if not isinstance(source, dict):
                continue

            normalized_sources.append(
                {
                    "title": source.get("title") or "Untitled",
                    "url": source.get("url") or "",
                    "site": source.get("site") or "",
                    "snippet": source.get("snippet") or "",
                    "favicon": source.get("favicon") or "",
                }
            )

        return normalized_sources

    def _source_key(self, source: dict[str, Any]) -> str:
        url = (source.get("url") or "").strip().lower()
        if url:
            return url
        title = (source.get("title") or "").strip().lower()
        snippet = (source.get("snippet") or "").strip().lower()
        return f"{title}|{snippet[:120]}"

    def _merge_sources(
        self, existing_sources: list[dict[str, Any]], new_sources: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged = list(existing_sources)
        seen = {self._source_key(source) for source in merged}

        for source in new_sources:
            key = self._source_key(source)
            if key in seen:
                continue

            seen.add(key)
            merged.append(source)
            if len(merged) >= _MAX_CONTEXT_SOURCES:
                break

        return merged

    def _build_context_from_sources(
        self, sources: list[dict[str, Any]], start_index: int = 1
    ) -> str:
        if not sources:
            return "No external data available."

        summary_lines: list[str] = []
        for index, source in enumerate(sources, start=start_index):
            title = source.get("title") or "Untitled"
            snippet = source.get("snippet") or ""
            summary_lines.append(f"[{index}] {title} - {snippet}")

        return "Search results:\n" + "\n".join(summary_lines)

    def _build_sources_payload(
        self,
        query: str,
        sources: list[dict[str, Any]],
        start_index: int = 1,
    ) -> dict[str, Any]:
        normalized_sources: list[dict[str, Any]] = []
        for index, source in enumerate(sources, start=start_index):
            normalized_sources.append(
                {
                    "index": index,
                    "title": source.get("title") or "Untitled",
                    "url": source.get("url") or "",
                    "site": source.get("site") or "",
                    "snippet": source.get("snippet") or "",
                    "favicon": source.get("favicon") or "",
                }
            )

        return {"query": query, "sources": normalized_sources}

    def _renumber_sources(
        self, sources: list[dict[str, Any]], start_index: int = 1
    ) -> list[dict[str, Any]]:
        renumbered: list[dict[str, Any]] = []
        for offset, source in enumerate(sources, start=start_index):
            renumbered.append(
                {
                    "index": offset,
                    "title": source.get("title") or "Untitled",
                    "url": source.get("url") or "",
                    "site": source.get("site") or "",
                    "snippet": source.get("snippet") or "",
                    "favicon": source.get("favicon") or "",
                }
            )
        return renumbered

    def _offset_context_indices(self, context: str, offset: int) -> str:
        if offset <= 0:
            return context

        def _replace(match: re.Match[str]) -> str:
            return f"[{int(match.group(1)) + offset}]"

        return re.sub(r"\[(\d+)]", _replace, context)

    def _build_planner_context(
        self,
        query: str,
        sources: list[dict[str, Any]],
        search_notes: list[str],
    ) -> str:
        context = self._build_context_from_sources(sources)
        notes = "\n".join([f"- {note}" for note in search_notes[-4:]])
        notes = notes or "- no prior searches"
        return (
            f"Question:\n{query}\n\n"
            f"Current Evidence:\n{context}\n\n"
            f"Search Notes:\n{notes}"
        )

    async def _run_search(self, search_query: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            _, tool_result, sources_payload = await asyncio.wait_for(
                self.tools["search"].run(search_query), timeout=_TOOL_TIMEOUT_SECONDS
            )
        except Exception:
            return "No external data available.", []

        return tool_result or "No external data available.", self._extract_sources(
            sources_payload
        )

    async def _plan_follow_up_queries(
        self,
        query: str,
        sources: list[dict[str, Any]],
        search_notes: list[str],
    ) -> list[str]:
        planner_context = self._build_planner_context(query, sources, search_notes)
        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=REACT_PLANNER_PROMPT),
                    HumanMessage(content=planner_context),
                ],
                max_tokens=160,
            )
        except Exception:
            return []

        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = self._extract_json_object(content)
        if not parsed:
            return []

        return self._sanitize_follow_up_queries(parsed.get("queries", []))

    def _get_required_follow_up_queries(self, query: str) -> list[str]:
        if not self._is_gold_total_market_cap_query(query):
            return []
        return [
            "World Gold Council total above-ground gold stock tonnes latest",
            "live gold spot price USD per ounce today",
        ]

    async def run(self, query: str, history: list[ChatTurn]) -> AsyncIterator[str]:
        yield _sse_event("status", "Understanding your query")

        if self._is_smalltalk(query):
            yield _sse_event("status", "Small talk detected")
            greeting = (
                "Hi! Ask me about gold or silver markets, prices, or outlook and I’ll help."
            )
            yield _sse_event("sources", json.dumps({"query": query, "sources": []}))
            yield _sse_event("token", greeting)
            yield _sse_event("done", "")
            return

        if not (self._is_metals_query(query) or self._history_mentions_metals(history)):
            yield _sse_event("status", "Outside metals scope")
            notice = (
                "I’m currently specialized in gold and silver. "
                "Ask me about gold/silver prices, market cap, or outlook."
            )
            yield _sse_event("sources", json.dumps({"query": query, "sources": []}))
            yield _sse_event("token", notice)
            yield _sse_event("done", "")
            return

        if self._is_ambiguous_market_cap_query(query):
            clarification = (
                "Please specify which asset or ticker you mean by market cap "
                "(for example: Bitcoin, AAPL, or GOLD), and I will fetch the latest value."
            )
            yield _sse_event("sources", json.dumps({"query": query, "sources": []}))
            yield _sse_event("token", clarification)
            yield _sse_event("done", "")
            return

        yield _sse_event("status", "Routing to metals specialist")
        should_search = self._should_search(query) or self._contains_youtube_url(query)
        all_sources: list[dict[str, Any]] = []
        executed_queries: list[str] = []

        if should_search:
            yield _sse_event("status", f"Searching the web for \"{query}\"")
            rewritten_query = await self._rewrite_query(query, history)
            initial_search_query = self._build_search_query(rewritten_query)

            search_notes: list[str] = []
            seen_queries = {initial_search_query.lower()}
            executed_queries = [initial_search_query]

            initial_note, initial_sources = await self._run_search(initial_search_query)
            search_notes.append(f"{initial_search_query} -> {initial_note}")
            all_sources = self._merge_sources(all_sources, initial_sources)

            required_queries = [
                required_query
                for required_query in self._get_required_follow_up_queries(query)
                if required_query.lower() not in seen_queries
            ]
            for required_query in required_queries:
                yield _sse_event("status", f"Searching the web for \"{required_query}\"")
                seen_queries.add(required_query.lower())
                executed_queries.append(required_query)
                required_note, required_sources = await self._run_search(required_query)
                search_notes.append(f"{required_query} -> {required_note}")
                all_sources = self._merge_sources(all_sources, required_sources)

            for _ in range(_MAX_REACT_STEPS):
                yield _sse_event("status", "Thinking through what else to fetch")
                follow_up_queries = await self._plan_follow_up_queries(
                    query=query,
                    sources=all_sources,
                    search_notes=search_notes,
                )
                follow_up_queries = [
                    follow_up_query
                    for follow_up_query in follow_up_queries
                    if follow_up_query.lower() not in seen_queries
                ]
                if not follow_up_queries:
                    break

                for follow_up_query in follow_up_queries:
                    yield _sse_event("status", f"Searching the web for \"{follow_up_query}\"")
                    seen_queries.add(follow_up_query.lower())
                    executed_queries.append(follow_up_query)
                    follow_up_note, follow_up_sources = await self._run_search(
                        follow_up_query
                    )
                    search_notes.append(f"{follow_up_query} -> {follow_up_note}")
                    all_sources = self._merge_sources(all_sources, follow_up_sources)

                if len(all_sources) >= _MAX_CONTEXT_SOURCES:
                    break

        yt_context = ""
        yt_sources: list[dict[str, Any]] = []
        if should_search:
            yield _sse_event("status", "Searching YouTube transcripts")
            yt_context, yt_sources = retrieve_youtube_context_with_sources(query)

        combined_sources: list[dict[str, Any]] = []
        context_sections: list[str] = []
        offset = 0

        if yt_context and yt_sources:
            yt_context = self._offset_context_indices(yt_context, offset)
            renumbered_yt_sources = self._renumber_sources(yt_sources, start_index=offset + 1)
            combined_sources.extend(renumbered_yt_sources)
            context_sections.append(f"YouTube context:\n{yt_context}")
            offset += len(renumbered_yt_sources)

        if all_sources:
            tavily_context = self._build_context_from_sources(
                all_sources, start_index=offset + 1
            )
            tavily_sources = self._build_sources_payload(
                query, all_sources, start_index=offset + 1
            )["sources"]
            combined_sources.extend(tavily_sources)
            context_sections.append(f"Web context:\n{tavily_context}")

        tool_result = "\n\n".join(context_sections) if context_sections else "No external data available."
        if tool_result == "No external data available." and executed_queries:
            attempts = "\n".join([f"- {attempt}" for attempt in executed_queries])
            tool_result = f"No external data available.\nSearch attempts:\n{attempts}"

        sources_payload = {"query": query, "sources": combined_sources}
        answer_instruction = (
            "Answer with one clear, direct number first and avoid vague uncertainty language. "
            "Prefer authoritative sources in context. "
            "If this is about total gold market cap today, compute a best-current estimate "
            "from latest above-ground stock and latest spot price shown in context. "
            "If exact real-time values are unavailable, still provide the best-current estimate and cite it."
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "Context:\n"
                    f"{tool_result}\n\n"
                    f"Question: {query}\n\n"
                    f"Instructions: {answer_instruction}"
                )
            ),
        ]

        yield _sse_event("status", "Thinking through the response")
        yield _sse_event("sources", json.dumps(sources_payload))
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield _sse_event("token", chunk.content)
        yield _sse_event("done", "")
