# Leyna — Web UI

A dependency-free single-page chat client for the Leyna backend, styled with
[Tailwind CSS](https://tailwindcss.com/). It is **served by the FastAPI backend
at `/`**, so there is nothing to install at runtime and no second dev server.

## What's in the box

- Streaming replies over `POST /chat/stream` (SSE), rendered token-by-token.
- A small, safe Markdown subset (bold, italics, inline code, fenced blocks,
  links) — everything is HTML-escaped before any markup is added.
- Per-message token counts, a stop button, copy-to-clipboard, and a
  conversation persisted in `localStorage`.
- A **debug drawer** with three tabs, backed by the `/debug/*` API:
  - **Usage** — cumulative token totals + a per-request table.
  - **Logs** — live server console (polled every 2 s, incremental via `after`).
  - **API key** — swap the runtime key, optionally persist it to `.env`, revert,
    and store an `X-Admin-Token` for locked-down deployments.

## Stack

| Piece      | Choice                                                        |
| ---------- | ------------------------------------------------------------- |
| CSS        | Tailwind CSS v4, CSS-first config (`@theme`, `@source`)        |
| JS         | Vanilla ES modules — no framework, no runtime dependencies     |
| Build      | `@tailwindcss/cli` (dev-only) via npm                          |

The app ships no third-party JavaScript. The only external request is the
optional Google Fonts `Inter` stylesheet; the design falls back to the system
font stack if it is blocked.

## Layout

```
web/
  src/
    input.css     # Tailwind entry: design tokens, base, components
    index.html    # markup (source)
    app.js        # chat + debug logic (source)
  build.mjs       # copies index.html and app.js into dist/
  dist/           # build output — served by the backend, committed
    app.css       # compiled + minified Tailwind
    index.html
    app.js
  smoke.mjs       # optional end-to-end browser check (see below)
  package.json
```

`dist/` is intentionally committed so `uvicorn` can serve the UI immediately on
a fresh clone. **Re-run `npm run build` after editing anything in `src/`.**

## Build

```bash
npm install        # first time only
npm run build      # compile CSS, then copy HTML/JS into dist/
npm run watch      # rebuild CSS on change (run build.mjs once first)
npm run dev        # build assets, then watch CSS
```

Then start the backend and open <http://127.0.0.1:8000/>:

```bash
cd ../backend && uvicorn app.main:app --reload
```

## Configuration

The UI calls the API on the same origin by default. To point it at a backend
elsewhere, edit the meta tag in `src/index.html` and rebuild:

```html
<meta name="leyna-api-base" content="http://localhost:8000" />
```

Because the backend enables CORS, cross-origin use works as long as the origin
is allowed (`CORS_ORIGINS`).

## Smoke test

`smoke.mjs` drives the real UI in headless Chrome over the DevTools Protocol
using Node's built-in `WebSocket` — no npm dependencies. It stubs
`/chat/stream`, so it never calls the paid API, but it does need the backend
running.

```bash
# in one terminal
cd ../backend && uvicorn app.main:app --port 8000

# in another
cd web && npm run smoke
# or: BASE_URL=http://127.0.0.1:8000 CHROME=chromium npm run smoke
```

It checks streaming + Markdown rendering, the token chip, history persistence,
every debug tab, Escape-to-close, and New chat. Exits non-zero on failure.

## Notes

- **Security.** The debug drawer can replace the server's API key and read
  server logs. Keep `DEBUG_ENABLED=false` (or set `ADMIN_TOKEN`) outside local
  development; the drawer has a field for the admin token.
- **`npm audit`.** Reports a high-severity advisory in `braces`, reached via
  `@tailwindcss/cli → @parcel/watcher → micromatch`. It is a **build-time only**
  dependency (file watching), it is not shipped to the browser, and no patched
  `braces` release exists. `npm audit fix --force` would only downgrade the CLI.
