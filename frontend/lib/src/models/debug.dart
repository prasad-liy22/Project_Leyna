/// Models for the backend's `/debug` API.
///
/// All fields are tolerant of missing values so a partial response never
/// crashes the panel.
library;

class ApiKeyInfo {
  const ApiKeyInfo(
      {required this.configured, required this.source, this.masked});

  final bool configured;

  /// Where the key came from: `env`, `debug-override`, or `unset`.
  final String source;

  /// Masked key for display, e.g. `e053…1JlI`.
  final String? masked;

  factory ApiKeyInfo.fromJson(Map<String, dynamic> json) => ApiKeyInfo(
        configured: json['configured'] == true,
        source: (json['source'] as String?) ?? 'unknown',
        masked: json['masked'] as String?,
      );
}

class UsageTotals {
  const UsageTotals({
    this.requests = 0,
    this.ok = 0,
    this.errors = 0,
    this.promptTokens = 0,
    this.completionTokens = 0,
    this.totalTokens = 0,
  });

  final int requests;
  final int ok;
  final int errors;
  final int promptTokens;
  final int completionTokens;
  final int totalTokens;

  factory UsageTotals.fromJson(Map<String, dynamic>? json) {
    final data = json ?? const <String, dynamic>{};
    int value(String key) => (data[key] as num?)?.toInt() ?? 0;
    return UsageTotals(
      requests: value('requests'),
      ok: value('ok'),
      errors: value('errors'),
      promptTokens: value('prompt_tokens'),
      completionTokens: value('completion_tokens'),
      totalTokens: value('total_tokens'),
    );
  }
}

class UsageRecord {
  const UsageRecord({
    required this.id,
    required this.time,
    required this.endpoint,
    required this.model,
    required this.ok,
    required this.latencyMs,
    this.promptTokens,
    this.completionTokens,
    this.totalTokens,
    this.error,
  });

  final int id;
  final String time;
  final String endpoint;
  final String model;
  final bool ok;
  final double latencyMs;
  final int? promptTokens;
  final int? completionTokens;
  final int? totalTokens;
  final String? error;

  factory UsageRecord.fromJson(Map<String, dynamic> json) => UsageRecord(
        id: (json['id'] as num?)?.toInt() ?? 0,
        time: (json['time'] as String?) ?? '',
        endpoint: (json['endpoint'] as String?) ?? '',
        model: (json['model'] as String?) ?? '',
        ok: json['ok'] == true,
        latencyMs: (json['latency_ms'] as num?)?.toDouble() ?? 0,
        promptTokens: (json['prompt_tokens'] as num?)?.toInt(),
        completionTokens: (json['completion_tokens'] as num?)?.toInt(),
        totalTokens: (json['total_tokens'] as num?)?.toInt(),
        error: json['error'] as String?,
      );
}

class UsageReport {
  const UsageReport({required this.totals, required this.records});

  final UsageTotals totals;
  final List<UsageRecord> records;

  factory UsageReport.fromJson(Map<String, dynamic> json) => UsageReport(
        totals: UsageTotals.fromJson(json['totals'] as Map<String, dynamic>?),
        records: [
          for (final record in (json['records'] as List? ?? const []))
            UsageRecord.fromJson(record as Map<String, dynamic>),
        ],
      );
}

class LogEntry {
  const LogEntry({
    required this.id,
    required this.time,
    required this.level,
    required this.logger,
    required this.message,
  });

  final int id;
  final String time;
  final String level;
  final String logger;
  final String message;

  factory LogEntry.fromJson(Map<String, dynamic> json) => LogEntry(
        id: (json['id'] as num?)?.toInt() ?? 0,
        time: (json['time'] as String?) ?? '',
        level: (json['level'] as String?) ?? 'INFO',
        logger: (json['logger'] as String?) ?? '',
        message: (json['message'] as String?) ?? '',
      );
}

class LogPage {
  const LogPage({required this.records, required this.lastId});

  final List<LogEntry> records;
  final int lastId;

  factory LogPage.fromJson(Map<String, dynamic> json) => LogPage(
        records: [
          for (final record in (json['records'] as List? ?? const []))
            LogEntry.fromJson(record as Map<String, dynamic>),
        ],
        lastId: (json['last_id'] as num?)?.toInt() ?? 0,
      );
}

class DebugState {
  const DebugState({
    required this.model,
    required this.baseUrl,
    required this.chatUrl,
    required this.systemPrompt,
    required this.requestTimeout,
    required this.apiKey,
    required this.logCount,
    required this.usage,
    required this.startedAt,
    required this.debugEnabled,
  });

  final String model;
  final String baseUrl;
  final String chatUrl;
  final String systemPrompt;
  final double requestTimeout;
  final ApiKeyInfo apiKey;
  final int logCount;
  final UsageTotals usage;
  final String startedAt;
  final bool debugEnabled;

  factory DebugState.fromJson(Map<String, dynamic> json) => DebugState(
        model: (json['model'] as String?) ?? '',
        baseUrl: (json['base_url'] as String?) ?? '',
        chatUrl: (json['chat_url'] as String?) ?? '',
        systemPrompt: (json['system_prompt'] as String?) ?? '',
        requestTimeout: (json['request_timeout'] as num?)?.toDouble() ?? 0,
        apiKey: ApiKeyInfo.fromJson(
          (json['api_key'] as Map<String, dynamic>?) ?? const {},
        ),
        logCount: (json['log_count'] as num?)?.toInt() ?? 0,
        usage: UsageTotals.fromJson(json['usage'] as Map<String, dynamic>?),
        startedAt: (json['started_at'] as String?) ?? '',
        debugEnabled: json['debug_enabled'] == true,
      );
}
