import json
from typing import AsyncIterator

from fastapi import HTTPException
from langchain_groq import ChatGroq

from app.agents.base_agent import BaseAgent
from app.agents.metals_agent import MetalsAgent
from app.agents.router import RouterAgent
from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.tools.search_tool import TavilySearchTool


def _sse_event(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "\n".join([f"data: {line}" for line in lines])
    return f"event: {event}\n{payload}\n\n"


class AgentManager:
    def __init__(self) -> None:
        self.llm = self._build_llm(model=settings.groq_model, temperature=0.2)
        self.router_llm = self._build_llm(model="llama3-8b-8192", temperature=0)
        self.tools = {"search": TavilySearchTool()}
        self.router = RouterAgent(self.router_llm)
        self.agents: dict[str, BaseAgent] = {
            "metals": MetalsAgent(self.tools, self.llm),
        }

    def _build_llm(self, model: str, temperature: float) -> ChatGroq:
        if not settings.groq_api_key:
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY is not set. Configure it in your .env file to enable Groq access.",
            )
        return ChatGroq(
            model=model,
            temperature=temperature,
            api_key=settings.groq_api_key,
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        agent_key = await self.router.route(request.message)
        if agent_key != "metals":
            notice = (
                "This MVP currently supports metals analysis only. "
                "Please ask a gold/silver question or include a metals ticker."
            )
            yield _sse_event("sources", json.dumps({"query": request.message, "sources": []}))
            yield _sse_event("token", notice)
            yield _sse_event("done", "")
            return

        agent = self.agents.get("metals")
        if agent is None:
            agent = MetalsAgent(self.tools, self.llm)

        async for event in agent.run(query=request.message, history=request.history):
            yield event
