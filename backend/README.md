# Nimna — Personal Assistant Backend

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
- **Short-term memory** — optional server-side transcripts, one per
  `conversation_id`, windowed to a token budget (see below).
- Serves a bundled Tailwind CSS web UI at `/` (see [`../web/`](../web/README.md)).
- Configurable model, endpoint, system prompt, and timeout via environment.
- Async HTTP with connection pooling (`httpx`).
- Interactive docs at `/docs` (Swagger UI) and `/redoc`.

## Project layout

```
app/
  config.py        # environment-driven settings
  prompts.py       # the default Nimna persona (system prompt)
  schemas.py       # request/response models
  ollama.py        # async client for the Ollama chat API
  conversations.py # in-memory short-term memory (transcripts + windowing)
  main.py          # FastAPI app and routes
  runtime.py       # process-wide debug state (logs, usage, API key)
  debug.py         # /debug routes
tests/
  test_chat.py          # API tests with the upstream API mocked
  test_prompts.py       # the default persona (contents + wiring)
  test_debug.py         # debug API tests
  test_conversations.py # short-term memory tests
  test_web.py           # static web UI serving tests
requirements.txt      # runtime dependencies
requirements-dev.txt  # test dependencies
.env.example          # template for your local .env
vercel.json           # Vercel function config (FastAPI entrypoint + duration)
VERCEL_DEPLOYMENT.md  # how to deploy this backend to Vercel
```

Two UIs live in sibling folders and both talk to this API:

- [`../web/`](../web/README.md) — HTML + Tailwind CSS, **served by this backend at `/`**.
- [`../frontend/`](../frontend/README.md) — Flutter (web) client, run separately.

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

| Field             | Type     | Required | Notes                                     |
| ----------------- | -------- | -------- | ----------------------------------------- |
| `messages`        | list     | yes      | At least one `{role, content}` message.   |
| `conversation_id` | string   | no       | Continue a server-side conversation (see below). |
| `model`           | string   | no       | Overrides `OLLAMA_MODEL` for this call.   |
| `temperature`     | float    | no       | `0.0`–`2.0`.                              |
| `system`          | string   | no       | Overrides the default system prompt.      |

`role` is one of `system`, `user`, or `assistant`. Without a
`conversation_id` the API is stateless: send the whole conversation each time to
keep context.

Responses gain two fields when memory is in play — the id to send next time, and
a summary of the transcript the model actually saw:

```json
{
  "model": "gemma4:31b-cloud",
  "message": {"role": "assistant", "content": "Your name is Ada."},
  "done": true,
  "prompt_tokens": 44,
  "completion_tokens": 8,
  "conversation_id": "0e0bb2a815b64fd8bf27181013d0f852",
  "memory": {
    "enabled": true,
    "stored_messages": 3,
    "window_messages": 3,
    "estimated_tokens": 44,
    "trimmed": false,
    "keep_first": false
  }
}
```

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

The final frame also carries `conversation_id` and `memory` when the request used
server-side memory. If the upstream call fails after streaming has started, the
stream ends with `data: {"done": true, "error": "..."}` — and nothing is
remembered.

### `GET /health`

```json
{"status": "ok", "version": "0.1.0", "model": "gemma4:31b-cloud", "configured": true, "memory_enabled": true}
```

## Short-term memory

It is on by default, but a request only uses it when it sends a
`conversation_id`. The server then owns the transcript and keeps it in process
memory:

- **Windowed transcript.** The newest messages that fit `MEMORY_TOKEN_BUDGET`
  are sent; older ones are dropped. Token counts are estimated from text length,
  so the budget is a guide rather than a hard limit.
- **Turn integrity.** A window never opens on an `assistant` message, so a reply
  is never shown without the question it answered. The current turn is always
  included, even if it alone exceeds the budget.
- **Two limits.** `MEMORY_MAX_MESSAGES` bounds what is stored;
  `MEMORY_TOKEN_BUDGET` bounds what is sent. With `MEMORY_KEEP_FIRST=true` the
  opening user message is pinned to the front when trimming.
- **Bounded and self-cleaning.** The store behaves as an LRU cache with a TTL:
  conversations idle longer than `MEMORY_TTL_MINUTES` are dropped, and the oldest
  are evicted past `MEMORY_MAX_CONVERSATIONS`.
- **Unknown ids are seeded.** If a request names a conversation the server does
  not have (first call, restart, or TTL expiry) it adopts the `messages` you sent
  as the history. If the server *does* know the conversation, it ignores the
  extra history and logs a debug warning; only the trailing user message is read.

Manage conversations directly:

| Method   | Path                   | Purpose                                    |
| -------- | ---------------------- | ------------------------------------------ |
| `POST`   | `/conversations`       | Start a new conversation, return its id.   |
| `GET`    | `/conversations/{id}`  | Read the stored transcript.                |
| `DELETE` | `/conversations/{id}`  | Forget it.                                 |

```bash
cid=$(curl -s -X POST http://127.0.0.1:8000/conversations | python3 -c 'import sys,json;print(json.load(sys.stdin)["conversation_id"])')

curl -s http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$cid\", \"messages\": [{\"role\": \"user\", \"content\": \"My name is Ada.\"}]}"

curl -s http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$cid\", \"messages\": [{\"role\": \"user\", \"content\": \"What is my name?\"}]}"
# → "Your name is Ada."
```

When `MEMORY_ENABLED=false` these routes report `409`/`404` and every request is
stateless again.

> **Single worker.** The store lives in one process, so run a single `uvicorn`
> worker (with or without `--reload`). With several workers the same
> `conversation_id` resolves to a different history in each one. It is also not
> durable — a restart forgets everything. Swap in Redis or a database behind the
> same handful of methods for anything more serious.

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
| `GET`    | `/debug/memory`     | Memory settings + stored conversations.      |
| `DELETE` | `/debug/memory`     | Forget every stored conversation.            |

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
| `SYSTEM_PROMPT`   | Built-in Nimna persona        | Default persona for every conversation; see `app/prompts.py`. |
| `REQUEST_TIMEOUT` | `120`                         | Upstream timeout in seconds.             |
| `MEMORY_ENABLED`  | `true`                        | Keep server-side transcripts.            |
| `MEMORY_TOKEN_BUDGET` | `3000`                    | Approximate tokens of history sent to the model. |
| `MEMORY_MAX_MESSAGES` | `60`                     | Most messages kept per conversation.     |
| `MEMORY_MAX_CONVERSATIONS` | `100`               | Most conversations kept (LRU).           |
| `MEMORY_TTL_MINUTES` | `180`                      | Forget a conversation after this long idle. |
| `MEMORY_KEEP_FIRST` | `false`                     | Pin the opening user message when trimming. |
| `CORS_ORIGINS`    | `*`                           | Comma-separated allowed browser origins. |
| `DEBUG_ENABLED`   | `true`                        | Expose the `/debug` routes.              |
| `ADMIN_TOKEN`     | *(empty)*                     | If set, `/debug` needs `X-Admin-Token`.  |
| `WEB_DIR`         | `<repo>/web/dist`             | Folder served at `/` as the web UI.      |

### Notes

- **Persona.** The default system prompt lives in
  [`app/prompts.py`](app/prompts.py) — one place to edit Nimna's tone. Override
  it for a single request with the `system` field, or globally with
  `SYSTEM_PROMPT`. It is prepended to every request, so it counts against the
  context window.
- **Model name.** `gemma4:31b-cloud` is verified to work against
  `https://ollama.com/api/chat`. The name returned by
  `curl https://ollama.com/api/tags` (for example `gemma4:31b`) also works, while
  the Ollama app/CLI uses `gemma4:cloud`. Change `OLLAMA_MODEL` to switch.
- **Local Ollama.** Set `OLLAMA_BASE_URL=http://localhost:11434` and any
  non-empty `OLLAMA_API_KEY` (a local server ignores it) to run fully offline.
- **One worker.** Short-term memory lives in this process; run a single
  `uvicorn` worker. See [Short-term memory](#short-term-memory).
- **Secrets.** Keep `.env` out of version control — it is already listed in
  `.gitignore`. Never commit your API key.

## Tests

The upstream API is mocked, so tests run offline and need no key:

```bash
uv pip install -r requirements-dev.txt
pytest
```

## Frontends

Two clients talk to this API over HTTP:

- **Web UI (recommended)** — [`../web/`](../web/README.md), an HTML + Tailwind
  CSS app that this backend serves at `/`. Because the assets are committed,
  just start the server and open <http://127.0.0.1:8000/>. Rebuild with
  `cd ../web && npm run build` after editing `web/src/`.
- **Flutter** — [`../frontend/`](../frontend/README.md), a Flutter web client
  you run separately with `flutter run -d chrome`.

## Deployment (Vercel)

This backend runs on Vercel's native Python/FastAPI runtime with **no code
changes** — Vercel auto-detects the `app` object in `app/main.py`. The only
project-specific files are `vercel.json` (entrypoint + function duration) and
the committed `requirements.txt`.

The one setting that makes or breaks it is the Vercel **Root Directory**, which
must be `backend`. See [`VERCEL_DEPLOYMENT.md`](VERCEL_DEPLOYMENT.md) for the
dashboard settings, environment variables, the diagnosis of the `x-powered-by:
Express` / `Cannot GET /health` response, troubleshooting, and serverless
limitations (notably: short-term memory is per-instance and ephemeral).
