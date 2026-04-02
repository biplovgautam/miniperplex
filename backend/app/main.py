import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.youtube.ingestion import start_ingestion_worker
from app.youtube.retriever import check_pinecone_connection
from app.youtube.storage import check_db_connection


app = FastAPI(title="Miniperplex Backend")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.on_event("startup")
def start_background_workers() -> None:
    check_db_connection()
    check_pinecone_connection()
    start_ingestion_worker()
