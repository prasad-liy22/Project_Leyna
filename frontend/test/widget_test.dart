import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:leyna_frontend/src/api/chat_backend.dart';
import 'package:leyna_frontend/src/models/chat_message.dart';
import 'package:leyna_frontend/src/screens/chat_screen.dart';

/// A stand-in backend so the UI can be tested without a running server.
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

void main() {
  testWidgets('sends a message and renders the reply', (tester) async {
    final backend = _FakeBackend(reply: 'Hi, I am Leyna.');
    await tester.pumpWidget(MaterialApp(home: ChatScreen(backend: backend)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'Hello');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    expect(find.text('Hello'), findsOneWidget);
    expect(find.text('Hi, I am Leyna.'), findsOneWidget);
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
}
