import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    tavily_url: str = os.getenv("TAVILY_URL", "https://api.tavily.com/search")
    pinecone_api_key: str | None = os.getenv("PINECONE_API_KEY")
    pinecone_index: str | None = os.getenv("PINECONE_INDEX")
    pinecone_namespace: str = os.getenv("PINECONE_NAMESPACE", "youtube")
    pinecone_embedding_model: str = os.getenv(
        "PINECONE_EMBEDDING_MODEL", "multilingual-e5-large"
    )
    youtube_db_url: str | None = os.getenv("YOUTUBE_DB_URL")
    youtube_db_path: str = os.getenv("YOUTUBE_DB_PATH", "data/youtube.sqlite3")
    youtube_channel_ids: list[str] = [
        channel_id.strip()
        for channel_id in os.getenv("YOUTUBE_CHANNEL_IDS", "").split(",")
        if channel_id.strip()
    ]
    youtube_ingestion_interval: int = int(os.getenv("YOUTUBE_INGESTION_INTERVAL", "600"))
    youtube_retrieval_k: int = int(os.getenv("YOUTUBE_RETRIEVAL_K", "6"))


settings = Settings()
