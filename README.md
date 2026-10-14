# Leyna — Personal Assistant

A personal assistant split into two parts:

| Folder      | What it is                                                        | Docs                                    |
| ----------- | ----------------------------------------------------------------- | --------------------------------------- |
| `backend/`  | FastAPI service that proxies chat requests to Ollama Cloud.        | [backend/README.md](backend/README.md)   |
| `frontend/` | Flutter (web) chat UI that talks to the backend.                   | [frontend/README.md](frontend/README.md) |

## Quick start

```bash
# 1. Backend
cd backend
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env          # then set OLLAMA_API_KEY
uvicorn app.main:app --reload # http://localhost:8000

# 2. Frontend (in another terminal)
cd frontend
flutter pub get
flutter run -d chrome
```

See the folder READMEs for details.
