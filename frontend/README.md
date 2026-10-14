# Leyna Frontend (Flutter)

A minimal chat UI for the [Leyna backend](../backend/README.md), targeting
**web**. It sends the conversation to `POST /chat` and shows the reply, with a
small connectivity indicator in the app bar.

## Requirements

- Flutter **3.22+** (stable) — checks the SDK with `flutter --version`.
  The pinned SDK constraint is Dart `^3.5.0`.
- The backend running locally (see the [backend README](../backend/README.md)).

## Setup

This project targets web, so you only need Flutter — no Android/iOS toolchain.

```bash
cd frontend
flutter pub get
```

## Run

Start the backend first:

```bash
cd backend
uvicorn app.main:app --reload
```

Then run the app. It points at `http://localhost:8000` by default:

```bash
flutter run -d chrome
```

Point it somewhere else with a dart-define:

```bash
# another host/port
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:9000

# Android emulator (host machine is 10.0.2.2)
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

## Test

```bash
flutter test
```

The widget tests use a fake backend, so they run without the server.

## How it talks to the API

| App action            | Backend call                     |
| --------------------- | -------------------------------- |
| App bar status dot     | `GET /health`                    |
| Sending a message      | `POST /chat`                     |
| Debug panel (below)    | `/debug/*`                       |

The whole conversation is sent on every request (the API is stateless), so the
assistant keeps context. The request body is:

```json
{ "messages": [ { "role": "user", "content": "Hi" } ] }
```

The reply is read from `message.content`.

## Debug panel

The **Debug** button in the app bar drops down a panel with three tabs:

- **Usage** — token consumption per request and in total. Each row shows
  `req <prompt> / res <completion>` tokens, the total, latency, model, and any
  error. Start here to see what a request and its response actually cost.
- **Logs** — a live console of the backend's application + uvicorn logs,
  polled every 2 seconds with a level filter and a clear button.
- **API Key** — view the current (masked) key and its source, then paste a new
  one and **Apply**. Optionally "Save to backend `.env`" to persist it across
  restarts; **Revert** drops the override and falls back to the environment key.

The key changer calls `POST /debug/api-key`; the change takes effect on the
backend for every client. The raw key is never sent back to the app — the panel
only ever shows a masked value.

These endpoints require `DEBUG_ENABLED=true` on the backend (the default).

## Project layout

```
lib/
  main.dart                       # app entry (wires the theme controller)
  src/
    config.dart                   # API_BASE_URL (dart-define)
    theme.dart                    # light/dark themes + ThemeController
    models/chat_message.dart      # ChatMessage + role
    models/debug.dart             # debug API models
    api/exceptions.dart           # ChatApiException
    api/chat_backend.dart         # ChatBackend interface + ChatApi client
    api/debug_api.dart            # DebugBackend interface + DebugApi client
    screens/chat_screen.dart      # chat UI
    screens/debug_panel.dart      # dropdown debug area
    widgets/message_bubble.dart   # a single bubble
test/
  widget_test.dart                # UI tests with fake backends
web/                              # web app shell (index.html, manifest)
```

## Theming

The app has both a light and a dark theme, seeded from the same colour
(`#6750A4`), and a toggle in the app bar (the icon shows which theme you would
switch *to*).

`ThemeController` holds a `ThemeMode` and starts at `ThemeMode.system`, so the
app follows the OS until the user picks a theme; that choice is then saved with
`shared_preferences` and restored on the next launch. Storage errors are
swallowed, so the app still runs if `shared_preferences` is unavailable (as in a
bare widget test).

The widget tests cover the toggle and the restore-on-startup path.

## Notes

- **CORS.** The backend must allow the browser's origin. It ships with
  `CORS_ORIGINS=*` for development — tighten this in production.
- **Streaming.** This UI uses the non-streaming `POST /chat`. A streaming
  variant is available at `POST /chat/stream` (Server-Sent Events) if you want
  to add token-by-token output later.
