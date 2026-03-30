from fastapi.testclient import TestClient

from app.main import app



def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "running ok"}



def test_chat_stream_requires_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post("/chat/stream", json={"message": "hi"})
    assert response.status_code == 503
    assert response.json()["detail"].startswith("GROQ_API_KEY")

