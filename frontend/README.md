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

The whole conversation is sent on every request (the API is stateless), so the
assistant keeps context. The request body is:

```json
{ "messages": [ { "role": "user", "content": "Hi" } ] }
```

The reply is read from `message.content`.

## Project layout

```
lib/
  main.dart                       # app entry
  src/
    config.dart                   # API_BASE_URL (dart-define)
    models/chat_message.dart      # ChatMessage + role
    api/chat_backend.dart         # ChatBackend interface + ChatApi client
    screens/chat_screen.dart      # chat UI
    widgets/message_bubble.dart   # a single bubble
test/
  widget_test.dart                # UI tests with a fake backend
web/                              # web app shell (index.html, manifest)
```

## Notes

- **CORS.** The backend must allow the browser's origin. It ships with
  `CORS_ORIGINS=*` for development — tighten this in production.
- **Streaming.** This UI uses the non-streaming `POST /chat`. A streaming
  variant is available at `POST /chat/stream` (Server-Sent Events) if you want
  to add token-by-token output later.
