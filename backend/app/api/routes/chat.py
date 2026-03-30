from fastapi import APIRouter

from app.schemas.chat import ChatRequest
from app.services.chat_service import stream_chat_response


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "running ok"}


@router.post("/chat/stream")
def chat_stream(request: ChatRequest):
    return stream_chat_response(request)
