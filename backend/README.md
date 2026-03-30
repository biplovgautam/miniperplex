# Miniperplex Backend

FastAPI service wired to Groq via LangChain, with Tavily search and citation-ready streaming chat.

## 📁 Project structure

```
backend/
├── app/
│   ├── main.py
│   ├── api/routes/chat.py
│   ├── agents/
│   ├── tools/
│   ├── schemas/
│   ├── core/
│   └── services/
├── tests/
├── Dockerfile
├── docker-compose.yml
├── main.py
└── requirements.txt
```

## ✅ What’s included
- FastAPI server with CORS enabled
- Gemini 1.5 Flash integration via `langchain-google-genai`
- Tavily-powered `web_search` tool
- Async streaming endpoint at `/chat/stream`

## 🔐 Environment
Set your API keys in the environment:

```
export GROQ_API_KEY="your_key_here"
export TAVILY_API_KEY="your_key_here"
```

## ▶️ Run
```
uvicorn app.main:app --reload
```

## 🧪 Tests
```
pytest
```

## Notes
- If `GOOGLE_API_KEY` is not set, `/chat/stream` returns a 503.
- The assistant formats citations like [1] and includes a Sources section.
