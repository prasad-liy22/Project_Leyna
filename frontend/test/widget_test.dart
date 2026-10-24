import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:leyna_frontend/main.dart';
import 'package:leyna_frontend/src/api/chat_backend.dart';
import 'package:leyna_frontend/src/api/debug_api.dart';
import 'package:leyna_frontend/src/models/chat_message.dart';
import 'package:leyna_frontend/src/models/debug.dart';
import 'package:leyna_frontend/src/screens/chat_screen.dart';
import 'package:leyna_frontend/src/screens/debug_panel.dart';
import 'package:leyna_frontend/src/theme.dart';

/// A stand-in chat backend so the UI can be tested without a running server.
class _FakeBackend implements ChatBackend {
  _FakeBackend({this.reply = 'Hello from the test!', this.fail = false});

  final String reply;
  final bool fail;
  final List<List<ChatMessage>> calls = [];

  @override
  Future<HealthStatus> health() async => const HealthStatus(
        reachable: true,
        configured: true,
        model: 'gemma4:31b-cloud',
      );

  @override
  Future<String> sendMessage(List<ChatMessage> messages) async {
    calls.add(messages);
    if (fail) throw ChatApiException('boom');
    return reply;
  }
}

/// A stand-in debug backend with canned data.
class _FakeDebugBackend implements DebugBackend {
  String source = 'env';
  String? lastAppliedKey;
  bool? lastPersist;

  @override
  Future<DebugState> debugState() async => DebugState(
        model: 'gemma4:31b-cloud',
        baseUrl: 'https://ollama.com',
        chatUrl: 'https://ollama.com/api/chat',
        systemPrompt: 'You are Nimna.',
        requestTimeout: 120,
        apiKey:
            ApiKeyInfo(configured: true, source: source, masked: 'env-…7890'),
        logCount: 1,
        usage: const UsageTotals(
            requests: 1,
            ok: 1,
            promptTokens: 11,
            completionTokens: 4,
            totalTokens: 15),
        startedAt: '2026-01-01T00:00:00Z',
        debugEnabled: true,
      );

  @override
  Future<UsageReport> usage({int limit = 20}) async => const UsageReport(
        totals: UsageTotals(
            requests: 1,
            ok: 1,
            promptTokens: 11,
            completionTokens: 4,
            totalTokens: 15),
        records: [
          UsageRecord(
            id: 1,
            time: '2026-01-01T00:00:00Z',
            endpoint: 'chat',
            model: 'gemma4:31b-cloud',
            ok: true,
            latencyMs: 857,
            promptTokens: 11,
            completionTokens: 4,
            totalTokens: 15,
          ),
        ],
      );

  @override
  Future<LogPage> logs(
          {int after = 0, int limit = 200, String level = 'INFO'}) async =>
      const LogPage(records: [], lastId: 0);

  @override
  Future<DebugState> setApiKey(String apiKey, {bool persist = false}) async {
    lastAppliedKey = apiKey;
    lastPersist = persist;
    source = apiKey.isEmpty ? 'env' : 'debug-override';
    return debugState();
  }

  @override
  Future<DebugState> clearApiKey() async {
    source = 'env';
    return debugState();
  }

  @override
  Future<void> clearLogs() async {}

  @override
  Future<void> clearUsage() async {}
}

void main() {
  testWidgets('sends a message and renders the reply', (tester) async {
    final backend = _FakeBackend(reply: 'Hi, I am Nimna.');
    await tester.pumpWidget(MaterialApp(home: ChatScreen(backend: backend)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'Hello');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    expect(find.text('Hello'), findsOneWidget);
    expect(find.text('Hi, I am Nimna.'), findsOneWidget);
    expect(backend.calls.single.last.text, 'Hello');
    expect(backend.calls.single.last.role, ChatRole.user);
  });

  testWidgets('shows a snackbar when the backend fails', (tester) async {
    final backend = _FakeBackend(fail: true);
    await tester.pumpWidget(MaterialApp(home: ChatScreen(backend: backend)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'Hello');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    expect(find.text('boom'), findsOneWidget);
  });

  testWidgets('debug button reveals the panel', (tester) async {
    final debug = _FakeDebugBackend();
    await tester.pumpWidget(MaterialApp(
      home: ChatScreen(backend: _FakeBackend(), debugBackend: debug),
    ));
    await tester.pump();
    await tester.pump();

    expect(find.text('Usage'), findsNothing);

    await tester.tap(find.text('Debug'));
    await tester.pump(); // toggle
    await tester.pump(); // let the initial load resolve

    expect(find.text('Usage'), findsOneWidget);
    expect(find.text('Logs'), findsOneWidget);
    expect(find.text('API Key'), findsOneWidget);

    // Dispose the tree so the panel's periodic timer is cancelled.
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('debug panel shows usage tokens', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: DebugPanel(backend: _FakeDebugBackend(), onClose: () {}),
      ),
    ));
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('req 11 / res 4 tok'), findsOneWidget);
    expect(find.text('Total tok'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('debug panel can change the API key', (tester) async {
    // Tall surface so the whole API-key form is laid out.
    tester.view.physicalSize = const Size(1000, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final debug = _FakeDebugBackend();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: DebugPanel(backend: debug, onClose: () {})),
    ));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('API Key'));
    await tester.pumpAndSettle();

    expect(find.textContaining('env-…7890'), findsOneWidget);

    await tester.enterText(
        find.widgetWithText(TextField, 'New API key'), 'brand-new-key');
    await tester.tap(find.text('Apply'));
    await tester.pump();
    await tester.pump();

    expect(debug.lastAppliedKey, 'brand-new-key');
    expect(find.textContaining('debug-override'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('app bar toggle switches between light and dark', (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final controller = ThemeController();
    addTearDown(controller.dispose);

    await tester.pumpWidget(NimnaApp(
      backend: _FakeBackend(),
      debugBackend: _FakeDebugBackend(),
      themeController: controller,
    ));
    await tester.pumpAndSettle();

    // No saved choice yet: the app follows the OS (light in tests).
    expect(controller.value, ThemeMode.system);
    expect(
      Theme.of(tester.element(find.byType(ChatScreen))).brightness,
      Brightness.light,
    );
    expect(find.byIcon(Icons.dark_mode_outlined), findsOneWidget);

    await tester.tap(find.byIcon(Icons.dark_mode_outlined));
    await tester.pumpAndSettle();

    expect(controller.value, ThemeMode.dark);
    expect(
      Theme.of(tester.element(find.byType(ChatScreen))).brightness,
      Brightness.dark,
    );
    // The icon flips so the next tap returns to light.
    expect(find.byIcon(Icons.light_mode_outlined), findsOneWidget);

    await tester.tap(find.byIcon(Icons.light_mode_outlined));
    await tester.pumpAndSettle();
    expect(controller.value, ThemeMode.light);
  });

  testWidgets('a saved preference is restored on startup', (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      ThemeController.preferenceKey: 'dark',
    });
    final controller = ThemeController();
    addTearDown(controller.dispose);

    await tester.pumpWidget(NimnaApp(
      backend: _FakeBackend(),
      debugBackend: _FakeDebugBackend(),
      themeController: controller,
    ));
    await tester.pumpAndSettle();

    expect(controller.value, ThemeMode.dark);
    expect(
      Theme.of(tester.element(find.byType(ChatScreen))).brightness,
      Brightness.dark,
    );
  });
}
