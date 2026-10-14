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
- A **light/dark theme toggle** in the header. The choice is remembered; on a
  first visit the UI follows the OS preference.
- A **debug drawer** with three tabs, backed by the `/debug/*` API:
  - **Usage** — cumulative token totals + a per-request table.
  - **Logs** — live server console (polled every 2 s, incremental via `after`).
  - **API key** — swap the runtime key, optionally persist it to `.env`, revert,
    and store an `X-Admin-Token` for locked-down deployments.

## Stack

| Piece      | Choice                                                        |
| ---------- | ------------------------------------------------------------- |
| CSS        | Tailwind CSS v4, CSS-first config (`@theme`, `@source`)        |
| Theming    | Semantic tokens (`--ink`, `--surface`, …) swapped per theme     |
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

## Theming

Colours are never hard-coded per component. `src/input.css` defines a small set
of **semantic tokens** and maps them to Tailwind colour names with
`@theme inline`, so `text-ink`, `bg-surface`, `border-line`, … all exist:

```css
@theme inline {
  --color-ink: var(--ink); /* → text-ink, bg-ink, border-ink, … */
}

:root  { --ink: #0f172a; }  /* light */
.dark  { --ink: #f1f5f9; }  /* dark  */
```

Tailwind v4 emits `color: var(--ink)` inside a utility rather than copying the
value, so redefining a token under `.dark` re-themes every element that uses it
— no duplicated class names, no `dark:` on every utility.

The `dark` variant is **class-based**, not media-query based:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

That lets an explicit user choice win over the OS setting. A tiny inline script
in `<head>` sets the class before the first paint, so there is no flash of the
wrong theme; `app.js` then keeps the toggle's icon, `aria-pressed` and
`localStorage` in sync, and only follows the OS while no explicit choice exists.

To add a themed colour, add the token in both `:root` and `.dark`, map it in
`@theme inline`, then use the resulting utility.

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
the light/dark toggle, every debug tab, Escape-to-close, and New chat. Exits
non-zero on failure.

## Notes

- **Security.** The debug drawer can replace the server's API key and read
  server logs. Keep `DEBUG_ENABLED=false` (or set `ADMIN_TOKEN`) outside local
  development; the drawer has a field for the admin token.
- **`npm audit`.** Reports a high-severity advisory in `braces`, reached via
  `@tailwindcss/cli → @parcel/watcher → micromatch`. It is a **build-time only**
  dependency (file watching), it is not shipped to the browser, and no patched
  `braces` release exists. `npm audit fix --force` would only downgrade the CLI.
