from fastapi.responses import StreamingResponse

from app.agents.agent_manager import AgentManager
from app.schemas.chat import ChatRequest


agent_manager = AgentManager()


def stream_chat_response(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        agent_manager.stream_chat(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
