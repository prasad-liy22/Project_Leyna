# Leyna — Personal Assistant

A personal assistant split into three parts:

| Folder      | What it is                                                          | Docs                                     |
| ----------- | ------------------------------------------------------------------- | ---------------------------------------- |
| `backend/`  | FastAPI service that proxies chat requests to Ollama Cloud.          | [backend/README.md](backend/README.md)   |
| `web/`      | HTML + Tailwind CSS chat UI. **Served by the backend at `/`.**        | [web/README.md](web/README.md)           |
| `frontend/` | Flutter (web) chat UI that talks to the backend.                     | [frontend/README.md](frontend/README.md) |

Both UIs ship a **light and a dark theme** with a toggle, and each remembers
your choice (the web UI falls back to your OS setting on a first visit).

The backend also keeps **short-term memory**: when a client sends a
`conversation_id`, the server holds the transcript and sends the model only the
newest slice that fits a token budget. See
[backend/README.md](backend/README.md#short-term-memory).

## Quick start

```bash
# 1. Backend (also serves the web UI at http://localhost:8000/)
cd backend
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env          # then set OLLAMA_API_KEY
uvicorn app.main:app --reload # http://localhost:8000

# 2. Web UI — nothing to install, it is already built and served at /
#    open http://localhost:8000/
```

### Rebuilding the web UI

The compiled assets in `web/dist/` are committed so the backend can serve them
out of the box. After editing anything in `web/src/`, rebuild:

```bash
cd web
npm install        # first time only
npm run build      # Tailwind -> dist/app.css, then copies HTML/JS
```

### Optional: the Flutter client

```bash
cd frontend
flutter pub get
flutter run -d chrome
```

See the folder READMEs for details.
