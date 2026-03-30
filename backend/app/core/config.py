import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    tavily_url: str = os.getenv("TAVILY_URL", "https://api.tavily.com/search")


settings = Settings()
