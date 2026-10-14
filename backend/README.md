# Leyna — Personal Assistant Backend

A small [FastAPI](https://fastapi.tiangolo.com/) backend for a personal
assistant. It exposes a chat API that forwards conversations to an external LLM
provider — by default [Ollama Cloud](https://docs.ollama.com/cloud) at
`https://ollama.com/api/chat` using the `gemma4:31b-cloud` model.

The API key lives in the server's environment; it is never exposed to clients.

This service lives in `backend/`. All commands below are run from that folder.

## Features

- `POST /chat` — send a conversation, get the full reply back.
- `POST /chat/stream` — receive the reply token-by-token as Server-Sent Events.
- `GET /health` — liveness probe plus configuration status.
- Configurable model, endpoint, system prompt, and timeout via environment.
- Async HTTP with connection pooling (`httpx`).
- Interactive docs at `/docs` (Swagger UI) and `/redoc`.

## Project layout

```
app/
  config.py     # environment-driven settings
  schemas.py    # request/response models
  ollama.py     # async client for the Ollama chat API
  main.py       # FastAPI app and routes
tests/
  test_chat.py        # API tests with the upstream API mocked
requirements.txt      # runtime dependencies
requirements-dev.txt  # test dependencies
.env.example          # template for your local .env
```

The Flutter chat UI lives in a sibling folder, [`../frontend/`](../frontend/README.md).

## Quickstart

This project was set up with [`uv`](https://docs.astral.sh/uv/), but plain
`venv` + `pip` works too.

```bash
# 1. Create and activate a virtual environment
uv venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
uv pip install -r requirements.txt

# 3. Add your API key
cp .env.example .env
# then edit .env and set OLLAMA_API_KEY=...  (get one at
# https://ollama.com/settings/keys)

# 4. Run the server
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> to try the endpoints interactively.

Using plain `venv` instead of `uv`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## API

### `POST /chat`

```bash
curl -s http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Give me a one-line dinner idea."}
    ]
  }'
```

```json
{
  "model": "gemma4:31b-cloud",
  "message": {"role": "assistant", "content": "How about lemon garlic pasta?"},
  "done": true,
  "prompt_tokens": 18,
  "completion_tokens": 9
}
```

Request fields:

| Field         | Type     | Required | Notes                                     |
| ------------- | -------- | -------- | ----------------------------------------- |
| `messages`    | list     | yes      | At least one `{role, content}` message.   |
| `model`       | string   | no       | Overrides `OLLAMA_MODEL` for this call.   |
| `temperature` | float    | no       | `0.0`–`2.0`.                              |
| `system`      | string   | no       | Overrides the default system prompt.      |

`role` is one of `system`, `user`, or `assistant`. The API is stateless: send
the whole conversation each time to keep context.

### `POST /chat/stream`

Same request body, but the reply arrives as Server-Sent Events:

```bash
curl -N http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Count to three."}]}'
```

```
data: {"delta": "One", "done": false}

data: {"delta": ", two", "done": false}

data: {"delta": ", three.", "done": false}

data: {"done": true, "model": "gemma4:31b-cloud", "prompt_tokens": 12, "completion_tokens": 6}
```

If the upstream call fails after streaming has started, the stream ends with
`data: {"done": true, "error": "..."}`.

### `GET /health`

```json
{"status": "ok", "version": "0.1.0", "model": "gemma4:31b-cloud", "configured": true}
```

## Debug API

Optional instrumentation for the frontend debug panel. Controlled by
`DEBUG_ENABLED` (on by default); when `ADMIN_TOKEN` is set every route below
requires a matching `X-Admin-Token` header.

| Method   | Path                | Purpose                                        |
| -------- | ------------------- | ---------------------------------------------- |
| `GET`    | `/debug/state`      | Config snapshot, with the API key **masked**.  |
| `POST`   | `/debug/api-key`    | Swap the API key at runtime.                   |
| `DELETE` | `/debug/api-key`    | Drop the override, revert to `.env`/env.       |
| `GET`    | `/debug/logs`       | Recent server log records (pollable).          |
| `DELETE` | `/debug/logs`       | Clear the log buffer.                          |
| `GET`    | `/debug/usage`      | Token totals + recent requests.                |
| `DELETE` | `/debug/usage`      | Clear usage history.                           |

Change the key at runtime (optionally persisting it to `.env`):

```bash
curl -s http://127.0.0.1:8000/debug/api-key \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-...", "persist": true}'
```

```json
{"api_key": {"configured": true, "masked": "sk-…9f2a", "source": "debug-override"}}
```

`GET /debug/usage` reports per-request and cumulative token consumption:

```json
{
  "totals": {"requests": 2, "ok": 1, "errors": 1,
             "prompt_tokens": 38, "completion_tokens": 4, "total_tokens": 42},
  "records": [
    {"id": 2, "endpoint": "chat", "model": "gemma4:31b-cloud", "ok": true,
     "latency_ms": 1661.8, "prompt_tokens": 38, "completion_tokens": 4, "total_tokens": 42},
    {"id": 1, "endpoint": "chat", "model": "gemma4:31b-cloud", "ok": false,
     "latency_ms": 572.7, "error": "Unauthorized"}
  ]
}
```

`GET /debug/logs` captures application + uvicorn logs. Poll incrementally with
`after` (pass the previous `last_id`) to fetch only new lines:

```bash
curl -s "http://127.0.0.1:8000/debug/logs?limit=100&after=0&level=INFO"
```

> **Security.** The key changer lets any caller who can reach this endpoint
> replace the server's API key, and the log console can expose request data.
> Keep `DEBUG_ENABLED=false` (or set a strong `ADMIN_TOKEN`) on anything that
> isn't local development.

## Configuration

All settings are read from the environment (or `.env`). See `.env.example`.

| Variable          | Default                       | Description                              |
| ----------------- | ----------------------------- | ---------------------------------------- |
| `OLLAMA_API_KEY`  | *(empty)*                     | Bearer token for ollama.com. **Required.** |
| `OLLAMA_BASE_URL` | `https://ollama.com`          | Use `http://localhost:11434` for local Ollama. |
| `OLLAMA_MODEL`    | `gemma4:31b-cloud`            | Model name sent to the API.              |
| `SYSTEM_PROMPT`   | `You are Leyna, ...`          | Default persona for every conversation.  |
| `REQUEST_TIMEOUT` | `120`                         | Upstream timeout in seconds.             |
| `CORS_ORIGINS`    | `*`                           | Comma-separated allowed browser origins. |
| `DEBUG_ENABLED`   | `true`                        | Expose the `/debug` routes.              |
| `ADMIN_TOKEN`     | *(empty)*                     | If set, `/debug` needs `X-Admin-Token`.  |

### Notes

- **Model name.** `gemma4:31b-cloud` is verified to work against
  `https://ollama.com/api/chat`. The name returned by
  `curl https://ollama.com/api/tags` (for example `gemma4:31b`) also works, while
  the Ollama app/CLI uses `gemma4:cloud`. Change `OLLAMA_MODEL` to switch.
- **Local Ollama.** Set `OLLAMA_BASE_URL=http://localhost:11434` and any
  non-empty `OLLAMA_API_KEY` (a local server ignores it) to run fully offline.
- **Secrets.** Keep `.env` out of version control — it is already listed in
  `.gitignore`. Never commit your API key.

## Tests

The upstream API is mocked, so tests run offline and need no key:

```bash
uv pip install -r requirements-dev.txt
pytest
```

## Frontend

A Flutter chat UI lives in [`../frontend/`](../frontend/README.md) and talks to
this API over HTTP. It targets web; start this backend, then run
`flutter run -d chrome` from that directory.
