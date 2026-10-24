import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/chat_message.dart';
import 'exceptions.dart';

export 'exceptions.dart';

/// Result of the `GET /health` probe.
class HealthStatus {
  const HealthStatus({
    required this.reachable,
    required this.configured,
    this.model,
  });

  /// Whether the backend answered at all.
  final bool reachable;

  /// Whether the backend has an API key configured for the LLM provider.
  final bool configured;

  /// The model the backend is configured to use, if reported.
  final String? model;
}

/// The contract the UI depends on, so it can be faked in tests.
abstract class ChatBackend {
  Future<HealthStatus> health();
  Future<String> sendMessage(List<ChatMessage> messages);
}

/// Talks to the Nimna FastAPI backend over HTTP.
class ChatApi implements ChatBackend {
  ChatApi({String? baseUrl, http.Client? client})
      : baseUrl = baseUrl ?? AppConfig.apiBaseUrl,
        _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  @override
  Future<HealthStatus> health() async {
    try {
      final response = await _client
          .get(_uri('/health'))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) {
        return const HealthStatus(reachable: true, configured: false);
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return HealthStatus(
        reachable: true,
        configured: body['configured'] == true,
        model: body['model'] as String?,
      );
    } catch (_) {
      return const HealthStatus(reachable: false, configured: false);
    }
  }

  @override
  Future<String> sendMessage(List<ChatMessage> messages) async {
    final http.Response response;
    try {
      response = await _client
          .post(
            _uri('/chat'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({
              'messages': [for (final message in messages) message.toJson()],
            }),
          )
          .timeout(const Duration(seconds: 120));
    } on TimeoutException {
      throw ChatApiException('The request timed out. Is the backend running?');
    } catch (error) {
      throw ChatApiException('Could not reach the API at $baseUrl.\n$error');
    }

    final Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw ChatApiException(
        'Unexpected response from the API (HTTP ${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }

    if (response.statusCode != 200) {
      throw ChatApiException(
        (body['detail'] as String?) ??
            'Request failed (HTTP ${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }

    final message = body['message'] as Map<String, dynamic>?;
    final content = message?['content'] as String?;
    if (content == null) {
      throw ChatApiException('The API response did not contain a message.');
    }
    return content;
  }
}
