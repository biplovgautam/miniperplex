import json

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.agents.prompts import REWRITE_PROMPT, SYSTEM_PROMPT
from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.tools.custom_tools import tavily_search


def sse_event(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "\n".join([f"data: {line}" for line in lines])
    return f"event: {event}\n{payload}\n\n"


class AgentManager:
    def get_llm(self) -> ChatGroq:
        if not settings.groq_api_key:
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY is not set. Configure it in your .env file to enable Groq access.",
            )
        return ChatGroq(
            model=settings.groq_model,
            temperature=0.2,
            api_key=settings.groq_api_key,
        )

    async def rewrite_query(self, llm: ChatGroq, request: ChatRequest) -> str:
        history_text = "\n".join(
            [f"{turn.role.title()}: {turn.content}" for turn in request.history[-6:]]
        ).strip()
        prompt_text = (
            f"Conversation so far:\n{history_text}\n\nUser question: {request.message}"
            if history_text
            else f"User question: {request.message}"
        )
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=REWRITE_PROMPT),
                    HumanMessage(content=prompt_text),
                ],
                max_tokens=32,
            )
        except Exception:
            return request.message

        rewritten = (response.content or "").strip().strip('"')
        return rewritten or request.message

    async def stream_chat(self, request: ChatRequest):
        llm = self.get_llm()
        rewritten_query = await self.rewrite_query(llm, request)
        _, tool_result, sources_payload = await tavily_search(rewritten_query)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            SystemMessage(content=tool_result),
            HumanMessage(content=request.message),
        ]

        yield sse_event("sources", json.dumps(sources_payload))
        async for chunk in llm.astream(messages):
            if chunk.content:
                yield sse_event("token", chunk.content)
        yield sse_event("done", "")
