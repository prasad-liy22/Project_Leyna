# Nimna — Personal Assistant

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

Nimna's tone comes from a single persona prompt in
[`backend/app/prompts.py`](backend/app/prompts.py): warm, playful, and
**Sinhala-first** (she understands Singlish and replies in Sinhala Unicode by
default). Edit that file to reshape her, or override it per request.

Both clients find the backend through a base URL — the web UI's
`leyna-api-base` meta tag (`web/src/index.html`) and Flutter's `API_BASE_URL`
(`frontend/lib/src/config.dart`). The committed build of each points at the
**deployed backend on Vercel**; see the folder READMEs to point either at a
local backend instead.

## Quick start

```bash
# 1. Backend (also serves the web UI at http://localhost:8000/)
cd backend
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env          # then set OLLAMA_API_KEY
uvicorn app.main:app --reload # http://localhost:8000

# 2. Web UI — nothing to install, it is already built and served at /
#    open http://localhost:8000/ (it talks to the deployed backend by
#    default; see web/README.md to point it at this local one)
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
