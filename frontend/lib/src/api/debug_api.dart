import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/debug.dart';
import 'exceptions.dart';

/// Debug features the panel depends on, so it can be faked in tests.
abstract class DebugBackend {
  Future<DebugState> debugState();
  Future<UsageReport> usage({int limit});
  Future<LogPage> logs({int after, int limit, String level});
  Future<DebugState> setApiKey(String apiKey, {bool persist});
  Future<DebugState> clearApiKey();
  Future<void> clearLogs();
  Future<void> clearUsage();
}

/// Talks to the backend's `/debug` endpoints.
class DebugApi implements DebugBackend {
  DebugApi({String? baseUrl, http.Client? client})
      : baseUrl = baseUrl ?? AppConfig.apiBaseUrl,
        _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  static const Duration _timeout = Duration(seconds: 15);

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<Map<String, dynamic>> _request(
    String method,
    String path, {
    Map<String, String>? query,
    Object? body,
  }) async {
    final http.Response response;
    try {
      final uri = _uri(path, query);
      const headers = {'Content-Type': 'application/json'};
      final future = switch (method) {
        'GET' => _client.get(uri).timeout(_timeout),
        'POST' => _client
            .post(uri, headers: headers, body: jsonEncode(body))
            .timeout(_timeout),
        'DELETE' => _client.delete(uri).timeout(_timeout),
        _ => throw ArgumentError('Unsupported method: $method'),
      };
      response = await future;
    } catch (error) {
      throw ChatApiException('Could not reach $baseUrl$path.\n$error');
    }

    if (response.body.isEmpty) {
      if (response.statusCode >= 400) {
        throw ChatApiException(
          'Debug API returned HTTP ${response.statusCode}.',
          statusCode: response.statusCode,
        );
      }
      return const {};
    }

    final Map<String, dynamic> decoded;
    try {
      decoded = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw ChatApiException(
        'Debug API returned an unexpected response (HTTP ${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }

    if (response.statusCode >= 400) {
      throw ChatApiException(
        (decoded['detail'] as String?) ??
            'Debug API error (HTTP ${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    return decoded;
  }

  @override
  Future<DebugState> debugState() async =>
      DebugState.fromJson(await _request('GET', '/debug/state'));

  @override
  Future<UsageReport> usage({int limit = 20}) async => UsageReport.fromJson(
      await _request('GET', '/debug/usage', query: {'limit': '$limit'}));

  @override
  Future<LogPage> logs(
          {int after = 0, int limit = 200, String level = 'INFO'}) async =>
      LogPage.fromJson(
        await _request('GET', '/debug/logs', query: {
          'after': '$after',
          'limit': '$limit',
          'level': level,
        }),
      );

  @override
  Future<DebugState> setApiKey(String apiKey, {bool persist = false}) async =>
      DebugState.fromJson(
        await _request(
          'POST',
          '/debug/api-key',
          body: {'api_key': apiKey, 'persist': persist},
        ),
      );

  @override
  Future<DebugState> clearApiKey() async =>
      DebugState.fromJson(await _request('DELETE', '/debug/api-key'));

  @override
  Future<void> clearLogs() async {
    await _request('DELETE', '/debug/logs');
  }

  @override
  Future<void> clearUsage() async {
    await _request('DELETE', '/debug/usage');
  }
}
