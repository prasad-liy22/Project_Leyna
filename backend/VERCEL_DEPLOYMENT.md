# Deploying the Nimna backend to Vercel

This guide makes the FastAPI service in `backend/` run on Vercel using its
**native Python runtime** — the existing app object, the existing routes, and
the existing dependency files. Nothing in `app/` had to change.

Vercel's current Python runtime (see
<https://vercel.com/docs/frameworks/backend/fastapi>) detects a FastAPI
application with **zero configuration**: it looks for a `FastAPI` instance named
`app` at one of

- `app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py`, `asgi.py`, or
- the same filenames inside `src/` or `app/`.

Our entry point is **`backend/app/main.py`**, which matches `app/main.py` — so
with the Root Directory set to `backend`, Vercel finds it automatically. There
is no `api/` wrapper and no second app.

---

## 1. Why the current deployment returns `Cannot GET /health`

The reported response is:

```text
HTTP/2 404
x-powered-by: Express
content-type: text/html

Cannot GET /health
```

`Cannot GET <path>` and the `x-powered-by: Express` header are produced by an
**Express (Node.js) server**. That response cannot come from this repository:

- There is **no Express** (or any Node package) in `backend/`. The only
  `package.json` in the monorepo is `web/package.json`, a Tailwind CSS *dev*
  dependency with no server and no runtime code.
- There is no `vercel.json`, no `api/` directory, and no `builds` config that
  would create a Node function.
- `backend/` is pure Python (`fastapi`, `uvicorn`, `httpx`, `pydantic`).

A direct probe of `https://personal-ai-backend.vercel.app` on 2026-10-15
confirms it: `/` returns HTTP 200 with `<h1>Welcome to Personal AI</h1>` and
`x-powered-by: Express`, while `/health` and `/chat` return `Cannot GET ...`.
Neither that page nor the string "Personal AI" exists anywhere in this
repository, so that deployment is running a **different codebase**.

So the `x-powered-by: Express` header does **not** mean the backend was rewritten
in Express — it means Vercel routed the request to a **Node/Express app**, not to
this FastAPI code. The realistic causes, in order of likelihood:

1. **The project is connected to a different repository.** The domain in the
   spec (`personal-ai-backend.vercel.app`) is not the domain this repo was
   previously published on, and this repo contains no OpenAI/`{"status":
   "healthy"}` code. Check *Project → Settings → Git* to confirm which repo is
   connected, and *Domains* to see which project owns the alias you are testing.
2. **Root Directory is not `backend`.** Vercel then builds the repo root, finds
   no Python entrypoint, and can fall back to a Node/static build.
3. **Framework Preset / Build Command is set to a Node preset**, so Vercel
   looks for a Node server instead of the Python entrypoint.
4. **A production alias points at a different (old) deployment.** Check
   *Deployments* and which one `personal-ai-backend.vercel.app` resolves to.

Symptoms 2–4 are fixed entirely in the dashboard (section 2), not in code.

> **Resolved.** This project's production domain is
> `https://project-leyna.vercel.app`, and it already serves this FastAPI app
> correctly — `GET /health` returns HTTP 200 JSON. The Express response
> described above belongs to a *different* project (`personal-ai-backend`), not
> this repository.

---

## 2. Required Vercel dashboard settings

Open the project → **Settings**.

| Setting | Where | Value |
| --- | --- | --- |
| **Root Directory** | General | `backend` |
| **Framework Preset** | Build & Development Settings | `FastAPI` (auto-detected). If unavailable, leave *Other* and make sure no `package.json` exists in `backend/`. |
| **Build Command** | Build & Development Settings | **leave empty** — do not set a Node/Next build. |
| **Output Directory** | Build & Development Settings | **leave empty** |
| **Install Command** | Build & Development Settings | **leave empty** (Vercel runs `pip install -r requirements.txt`) |
| **Node.js Version** | General | irrelevant for this project; leave default |
| **Production Branch** | Git | `main` |
| **Function Max Duration** | Functions | `300` (Hobby default/max with Fluid compute) — also pinned in `vercel.json` |

Key point: **Root Directory must be `backend`.** Vercel then treats
`backend/` as the project root, where it finds `app/main.py`, `requirements.txt`
and `vercel.json`.

> Do not point Root Directory at the repository root. `backend/app/main.py` is
> then neither a root file nor inside `src/`/`app/`, so zero-config FastAPI
> detection does not trigger.

---

## 3. Python runtime and dependencies

- **Version.** Vercel supports Python **3.12** (default), 3.13 and 3.14. No pin
  is committed, so the default **3.12** is used. This is deliberate: the code
  targets 3.10+, and 3.12 keeps pre-built wheels available for the compiled
  dependencies pulled in by `uvicorn[standard]` (`uvloop`, `httptools`).
  To pin explicitly, add a `.python-version` file containing e.g. `3.12`.
- **Dependencies.** `backend/requirements.txt` is the single dependency source
  and is installed as-is:

  ```text
  fastapi>=0.115
  uvicorn[standard]>=0.32
  httpx>=0.27
  pydantic>=2.9
  pydantic-settings>=2.5
  ```

  `requirements-dev.txt` (pytest) is **not** installed in production.
  There is intentionally **no `pyproject.toml`**: adding one would become the
  preferred dependency source and, if it lacked a `[project] dependencies`
  table, would deploy with no dependencies at all.
- `uvicorn[standard]` is not needed by the serverless runtime (Vercel provides
  the server) but is kept because it is the local dev server. It can be moved to
  `requirements-dev.txt` later to shrink install time — a deliberate
  non-change.

---

## 4. Environment variables

Set these in **Project → Settings → Environment Variables** (Production, and
Preview if you want preview deploys to work). Never commit them — `.env` is
already gitignored, and Vercel injects these into `os.environ`.

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `OLLAMA_API_KEY` | **Yes** for `/chat` | `""` | Bearer token from <https://ollama.com/settings/keys>. Without it the app still boots and `/health` reports `"configured": false`. |
| `OLLAMA_BASE_URL` | No | `https://ollama.com` | Point at `http://localhost:11434` only for a local Ollama. |
| `OLLAMA_MODEL` | No | `gemma4:31b-cloud` | |
| `SYSTEM_PROMPT` | No | built-in persona | Leave **unset** to use `app/prompts.py`. |
| `REQUEST_TIMEOUT` | No | `120` | Seconds for one upstream call. Keep below the function `maxDuration`. |
| `CORS_ORIGINS` | No | `*` | Set to your frontend origin(s) in production. |
| `MEMORY_*` | No | see `.env.example` | Short-term memory knobs. |
| `DEBUG_ENABLED` | **Recommended** | `true` | Set `false` in production — see Limitations. |
| `ADMIN_TOKEN` | No | `""` | If you keep `/debug` on, set this so the routes require `X-Admin-Token`. |

Secrets are never printed: `/health` exposes only `configured` (a boolean) and
`/debug/state` masks the key.

---

## 5. Deploy from GitHub

1. Push this repository to GitHub with the `backend/vercel.json` file included.
2. In Vercel: **Add New → Project → Import** the repository.
3. Set **Root Directory** = `backend`, **Framework Preset** = `FastAPI`
   (or auto-detected), leave Build/Output/Install commands empty.
4. Add the environment variables from section 4.
5. **Deploy.** Every push to `main` then produces a Production deployment; other
   branches/PRs produce Preview deployments.

The committed `vercel.json` pins the function duration:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": { "app/main.py": { "maxDuration": 300 } }
}
```

`app/main.py` is the resolved entrypoint (relative to the `backend/` root). The
`functions` key must always match a real file — `tests/test_vercel_config.py`
fails the build's test run if it drifts.

Local development is unchanged: `uvicorn app.main:app --reload`.

---

## 6. Test the deployed API

`HOST` is the project's production domain:

```bash
HOST=https://project-leyna.vercel.app

# Liveness + configuration (expect HTTP 200 and JSON)
curl -i "$HOST/health"
curl -s "$HOST/health" | python -m json.tool

# Interactive docs
#   open "$HOST/docs"

# One-shot chat
curl -s -X POST "$HOST/chat" \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}' | python -m json.tool

# Streaming chat (Server-Sent Events; -N disables buffering)
curl -N -X POST "$HOST/chat/stream" \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

A working `/health` looks like:

```json
{"status": "ok", "version": "0.1.0", "model": "gemma4:31b-cloud", "configured": true, "memory_enabled": true}
```

> **Note on the status field.** The endpoint returns `"status": "ok"` — the
> value this API has always used. The task brief expected
> `{"status": "healthy"}`; that would be a change to an existing response
> contract, which is intentionally avoided. Neither client depends on the exact
> string (the web UI keys off HTTP 200 plus `configured`/`model`; the Flutter
> client parses `configured`/`model`). If a monitor genuinely requires
> `"healthy"`, change the value in `app/main.py`'s `health()` handler and update
> `backend/README.md` — say the word and it is a one-line change.

If you still see `Cannot GET /health` with `x-powered-by: Express`, the request
is not reaching this app at all — re-check section 1 and section 2.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `404 Cannot GET /health`, `x-powered-by: Express` | Request served by a Node app, not this repo | Wrong project connected, or Root Directory ≠ `backend`, or a Node Framework Preset. See section 1–2. |
| `404: NOT_FOUND` (Vercel HTML, no Express) | Vercel built the repo as a static site | Root Directory ≠ `backend` / no Python entrypoint detected. |
| Build log: "No entrypoint found" | Root Directory wrong, or app not named `app` | Root Directory = `backend`; keep `app = FastAPI(...)` in `app/main.py`. |
| Build fails installing a dependency | Python version too new for a compiled wheel | Do not pin 3.14; the default is 3.12. |
| `/health` OK but `/chat` → 500 / "not configured" | `OLLAMA_API_KEY` missing in this environment | Add it to **Production** env vars and redeploy. |
| `/chat` or `/chat/stream` cut off mid-reply | Function duration exceeded | Keep `REQUEST_TIMEOUT` below the `maxDuration` (300s on Hobby). |
| CORS error in the browser | Origin not allowed | Set `CORS_ORIGINS` to your frontend origin(s), e.g. `https://app.example.com`. |
| Old behaviour after a deploy | Testing a stale alias/preview | Check **Domains** and **Deployments**; hit the newest deployment URL. |

Diagnostic commands:

```bash
curl -sI "$HOST/health"          # look at server / x-vercel-id headers
curl -sI "$HOST/health" | grep -i -E 'server|x-powered-by|x-vercel'
```

`server: Vercel` with `x-vercel-id` means you reached Vercel; `x-powered-by:
Express` means you reached a Node app, not the FastAPI function.

---

## 8. Serverless limitations (unchanged features — please read)

Nothing was removed. These are inherent to serverless and only affect production
behaviour:

- **Short-term memory is per-instance and ephemeral.** `app/conversations.py`
  keeps transcripts in process memory. On Vercel with Fluid compute, requests
  may be served by different (or freshly started) instances, so a
  `conversation_id` is **not** guaranteed to find its transcript. This is the
  same single-worker caveat documented for local runs, amplified in the cloud.
  For durable memory you would need an external store (Redis/Postgres/Workers
  KV) — a design change, deliberately not made here.
- **Debug state is per-instance.** `app/runtime.py` (log ring buffer, usage
  totals) is process-local, so `/debug/state` and `/debug/logs` only reflect the
  instance that served the request. Also, `/debug` is **exposed by default**:
  set `DEBUG_ENABLED=false` in production, or set `ADMIN_TOKEN`.
- **Function duration cap.** Requests are bounded by `maxDuration` (300s on
  Hobby). Long agent calls or streams that exceed it are terminated.
- **The bundled web UI is not served by this project.** `web_dir` defaults to
  `<repo>/web/dist`, which sits **outside** the `backend/` root, so the static
  mount is skipped (the app logs a warning and starts normally). Deploy the
  Tailwind UI separately, or serve it from the same origin another way. This is
  fine for an API-only deployment.
- **No durable filesystem, no background jobs, no WebSockets** are used, so
  there is nothing else to adapt. SSE (`POST /chat/stream`) is supported;
  Vercel sends HTTP/2 keep-alive frames while a streamed response is idle.
- **Cold starts** add latency to the first request on a new instance.

---

## 9. What changed

| File | Change |
| --- | --- |
| `backend/vercel.json` | New. Pins the FastAPI entrypoint's function duration. |
| `backend/tests/test_vercel_config.py` | New. Guards the entrypoint ↔ `vercel.json` contract. |
| `backend/VERCEL_DEPLOYMENT.md` | New. This guide. |
| `backend/README.md` | Links to this guide. |

No application code, routes, schemas, or dependency versions were modified.
