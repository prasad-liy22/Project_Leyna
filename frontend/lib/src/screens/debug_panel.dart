import 'dart:async';

import 'package:flutter/material.dart';

import '../api/debug_api.dart';
import '../models/debug.dart';

/// The dropdown debug area: token usage, the server log console, and a runtime
/// API key changer.
///
/// While visible it polls the backend every two seconds.
class DebugPanel extends StatefulWidget {
  const DebugPanel({
    super.key,
    required this.backend,
    required this.onClose,
    this.onApiKeyChanged,
    this.pollInterval = const Duration(seconds: 2),
  });

  final DebugBackend backend;
  final VoidCallback onClose;

  /// Called after the API key changes, so the app can re-check `/health`.
  final VoidCallback? onApiKeyChanged;

  final Duration pollInterval;

  @override
  State<DebugPanel> createState() => _DebugPanelState();
}

class _DebugPanelState extends State<DebugPanel> {
  final TextEditingController _keyController = TextEditingController();
  final ScrollController _logScroll = ScrollController();
  final TextEditingController _backendController = TextEditingController();

  DebugState? _state;
  UsageReport? _usage;
  List<LogEntry> _logs = [];
  int _lastLogId = 0;
  String _level = 'INFO';
  String? _error;
  bool _loading = true;
  bool _busy = false;
  bool _obscure = true;
  bool _persist = false;
  String? _keyStatus;
  String? _backendStatus;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refreshAll();
    _timer = Timer.periodic(widget.pollInterval, (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _keyController.dispose();
    _logScroll.dispose();
    _backendController.dispose();
    super.dispose();
  }

  /// Reloads everything. Safe to call from [initState] (no synchronous setState).
  Future<void> _refreshAll() async {
    _logs = [];
    _lastLogId = 0;
    try {
      final state = await widget.backend.debugState();
      final usage = await widget.backend.usage(limit: 20);
      final page = await widget.backend.logs(after: 0, level: _level);
      if (!mounted) return;
      setState(() {
        _state = state;
        _usage = usage;
        _logs = page.records;
        _lastLogId = page.lastId;
        _error = null;
        _loading = false;
      });
      _scrollLogsToBottom();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
        _loading = false;
      });
    }
  }

  void _onRefreshPressed() {
    setState(() => _loading = true);
    _refreshAll();
  }

  Future<void> _poll() async {
    await Future.wait([_loadUsage(), _pollLogs()]);
  }

  Future<void> _loadUsage() async {
    try {
      final usage = await widget.backend.usage(limit: 20);
      if (mounted) setState(() => _usage = usage);
    } catch (_) {
      // Usage is best-effort; the state load surfaces hard errors.
    }
  }

  Future<void> _pollLogs() async {
    try {
      final follow = _isAtLogBottom();
      final page = await widget.backend.logs(after: _lastLogId, level: _level);
      if (!mounted) return;
      setState(() {
        _logs = [..._logs, ...page.records];
        if (_logs.length > 500) {
          _logs = _logs.sublist(_logs.length - 500);
        }
        // Advance only to the last record actually received, so a burst larger
        // than `limit` between polls is fetched on the next tick instead of
        // being skipped.
        _lastLogId =
            page.records.isNotEmpty ? page.records.last.id : page.lastId;
      });
      if (follow) _scrollLogsToBottom();
    } catch (_) {
      // Ignore transient polling failures.
    }
  }

  /// Whether the log console is scrolled to (or near) the bottom.
  bool _isAtLogBottom() {
    if (!_logScroll.hasClients) return true;
    final position = _logScroll.position;
    return position.maxScrollExtent - position.pixels <= 40;
  }

  void _scrollLogsToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_logScroll.hasClients) return;
      _logScroll.jumpTo(_logScroll.position.maxScrollExtent);
    });
  }

  Future<void> _applyKey() async {
    final key = _keyController.text.trim();
    setState(() {
      _busy = true;
      _keyStatus = null;
    });
    try {
      final state = await widget.backend.setApiKey(key, persist: _persist);
      if (!mounted) return;
      setState(() {
        _state = state;
        _keyController.clear();
        _keyStatus = key.isEmpty ? 'Override cleared.' : 'API key updated.';
      });
      widget.onApiKeyChanged?.call();
    } catch (error) {
      if (mounted) setState(() => _keyStatus = 'Failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _clearOverride() async {
    setState(() {
      _busy = true;
      _keyStatus = null;
    });
    try {
      final state = await widget.backend.clearApiKey();
      if (!mounted) return;
      setState(() {
        _state = state;
        _keyStatus = 'Reverted to the environment key.';
      });
      widget.onApiKeyChanged?.call();
    } catch (error) {
      if (mounted) setState(() => _keyStatus = 'Failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _clearLogs() async {
    try {
      await widget.backend.clearLogs();
      if (mounted) {
        setState(() {
          _logs = [];
          _lastLogId = 0;
        });
      }
    } catch (_) {}
  }

  Future<void> _clearUsage() async {
    try {
      await widget.backend.clearUsage();
      if (mounted) await _loadUsage();
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final height = (MediaQuery.sizeOf(context).height * 0.5)
        .clamp(240.0, 440.0)
        .toDouble();

    return DefaultTabController(
      length: 4,
      child: Material(
        color: colors.surfaceContainer,
        child: Container(
          height: height,
          width: double.infinity,
          decoration: BoxDecoration(
            border: Border(bottom: BorderSide(color: colors.outlineVariant)),
          ),
          child: Column(
            children: [
              _buildHeader(context),
              if (_error != null)
                Container(
                  width: double.infinity,
                  color: colors.errorContainer,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Text(
                    _error!,
                    style:
                        TextStyle(color: colors.onErrorContainer, fontSize: 12),
                  ),
                ),
              const TabBar(
                isScrollable: true,
                tabs: [
                  Tab(icon: Icon(Icons.bar_chart, size: 18), text: 'Usage'),
                  Tab(icon: Icon(Icons.terminal, size: 18), text: 'Logs'),
                  Tab(icon: Icon(Icons.key, size: 18), text: 'API Key'),
                  Tab(icon: Icon(Icons.swap_horiz, size: 18), text: 'Backend'),
                ],
              ),
              Expanded(
                child: _loading && _state == null
                    ? const Center(child: CircularProgressIndicator())
                    : TabBarView(
                        children: [
                          _UsageTab(
                            usage: _usage,
                            onClear: _clearUsage,
                          ),
                          _LogsTab(
                            logs: _logs,
                            level: _level,
                            scrollController: _logScroll,
                            onLevelChanged: (level) {
                              setState(() {
                                _level = level;
                                _logs = [];
                                _lastLogId = 0;
                              });
                              _pollLogs();
                            },
                            onClear: _clearLogs,
                          ),
                          _buildApiKeyTab(context),
                          _buildBackendTab(context),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 6, 0),
      child: Row(
        children: [
          Icon(Icons.bug_report, size: 18, color: theme.colorScheme.primary),
          const SizedBox(width: 8),
          Text('Debug', style: theme.textTheme.titleSmall),
          const Spacer(),
          IconButton(
            tooltip: 'Refresh',
            iconSize: 18,
            onPressed: _loading ? null : _onRefreshPressed,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: 'Close',
            iconSize: 18,
            onPressed: widget.onClose,
            icon: const Icon(Icons.close),
          ),
        ],
      ),
    );
  }

  Widget _buildApiKeyTab(BuildContext context) {
    final theme = Theme.of(context);
    final key = _state?.apiKey;
    final source = key?.source ?? 'unknown';
    final statusColor =
        key?.configured == true ? Colors.green : theme.colorScheme.error;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Icon(Icons.vpn_key, size: 16, color: statusColor),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                key == null
                    ? 'API key status unavailable'
                    : 'Current: ${key.masked ?? "(none)"}  ·  source: $source',
                style: theme.textTheme.bodySmall,
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _keyController,
          obscureText: _obscure,
          enabled: !_busy,
          decoration: InputDecoration(
            labelText: 'New API key',
            hintText: 'Paste the key from ollama.com/settings/keys',
            isDense: true,
            border: const OutlineInputBorder(),
            suffixIcon: IconButton(
              tooltip: _obscure ? 'Show' : 'Hide',
              icon: Icon(_obscure ? Icons.visibility : Icons.visibility_off,
                  size: 18),
              onPressed: () => setState(() => _obscure = !_obscure),
            ),
          ),
          onSubmitted: (_) => _applyKey(),
        ),
        const SizedBox(height: 8),
        SwitchListTile(
          value: _persist,
          onChanged: _busy ? null : (value) => setState(() => _persist = value),
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: const Text('Save to backend .env',
              style: TextStyle(fontSize: 13)),
          subtitle: const Text('Survives a server restart',
              style: TextStyle(fontSize: 11)),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            FilledButton.icon(
              onPressed: _busy ? null : _applyKey,
              icon: const Icon(Icons.save, size: 16),
              label: const Text('Apply'),
            ),
            const SizedBox(width: 8),
            OutlinedButton(
              onPressed: _busy ? null : _clearOverride,
              child: const Text('Revert'),
            ),
            const Spacer(),
            if (_busy)
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
          ],
        ),
        if (_keyStatus != null) ...[
          const SizedBox(height: 12),
          Text(_keyStatus!, style: theme.textTheme.bodySmall),
        ],
        const SizedBox(height: 12),
        Text(
          'Changes apply to the backend process for every client. '
          'The key is never sent to this app once saved.',
          style: theme.textTheme.bodySmall?.copyWith(fontSize: 11),
        ),
      ],
    );
  }

  Widget _buildBackendTab(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Switch backend', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(
          'Current: ${_state?.baseUrl ?? 'unknown'}',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _backendController,
          enabled: !_busy,
          decoration: const InputDecoration(
            labelText: 'Backend URL',
            hintText: 'http://localhost:8000 or https://example.com',
            isDense: true,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () => _backendController.text = 'http://localhost:8000',
              child: const Text('Localhost :8000'),
            ),
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () => _backendController.text =
                      'https://project-leyna.vercel.app',
              child: const Text('Remote'),
            ),
            OutlinedButton(
              onPressed: _busy ? null : () => _backendController.text = '',
              child: const Text('Same origin'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            FilledButton.icon(
              onPressed: _busy ? null : _applyBackend,
              icon: const Icon(Icons.check, size: 16),
              label: const Text('Apply'),
            ),
            const Spacer(),
            if (_busy)
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
          ],
        ),
        if (_backendStatus != null) ...[
          const SizedBox(height: 12),
          Text(_backendStatus!, style: theme.textTheme.bodySmall),
        ],
        const SizedBox(height: 12),
        Text(
          'This app uses a build-time base URL (dart-define). To switch at runtime you need to rebuild or use a different build. '
          'For web/dev, you can also pass --dart-define=API_BASE_URL=...',
          style: theme.textTheme.bodySmall?.copyWith(fontSize: 11),
        ),
      ],
    );
  }

  Future<void> _applyBackend() async {
    final url = _backendController.text.trim();
    setState(() {
      _busy = true;
      _backendStatus = null;
    });
    try {
      // We can't change compile-time config at runtime in Flutter; just report the target.
      await Future.delayed(const Duration(milliseconds: 200));
      if (!mounted) return;
      setState(() {
        _backendStatus = url.isEmpty
            ? 'Target: same origin (use --dart-define=API_BASE_URL or rebuild).'
            : 'Target: $url (use --dart-define=API_BASE_URL or rebuild).';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _UsageTab extends StatelessWidget {
  const _UsageTab({required this.usage, required this.onClear});

  final UsageReport? usage;
  final Future<void> Function() onClear;

  @override
  Widget build(BuildContext context) {
    final totals = usage?.totals ?? const UsageTotals();
    final records = usage?.records ?? const <UsageRecord>[];

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _Stat(label: 'Requests', value: '${totals.requests}'),
            _Stat(label: 'Prompt tok', value: '${totals.promptTokens}'),
            _Stat(label: 'Compl. tok', value: '${totals.completionTokens}'),
            _Stat(label: 'Total tok', value: '${totals.totalTokens}'),
            _Stat(label: 'Errors', value: '${totals.errors}'),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Text('Recent requests',
                style: Theme.of(context).textTheme.labelMedium),
            const Spacer(),
            TextButton.icon(
              onPressed: onClear,
              icon: const Icon(Icons.delete_outline, size: 16),
              label: const Text('Clear'),
            ),
          ],
        ),
        if (records.isEmpty)
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('No requests recorded yet.',
                style: TextStyle(fontSize: 12)),
          ),
        for (final record in records) _UsageTile(record: record),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 10)),
          Text(
            value,
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _UsageTile extends StatelessWidget {
  const _UsageTile({required this.record});

  final UsageRecord record;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tokens =
        'req ${record.promptTokens ?? '-'} / res ${record.completionTokens ?? '-'} tok'
        '${record.totalTokens != null ? ' (${record.totalTokens} total)' : ''}';

    return ListTile(
      dense: true,
      visualDensity: VisualDensity.compact,
      leading: Icon(
        record.ok ? Icons.check_circle : Icons.error,
        size: 16,
        color: record.ok ? Colors.green : theme.colorScheme.error,
      ),
      title: Text(
        '${record.endpoint} · ${record.model}',
        style: theme.textTheme.bodySmall,
      ),
      subtitle: Text(
        '$tokens · ${record.latencyMs.toStringAsFixed(0)} ms'
        '${record.error != null ? '\n${record.error}' : ''}',
        style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
      ),
      trailing: Text(_timeOf(record.time), style: theme.textTheme.labelSmall),
    );
  }
}

class _LogsTab extends StatelessWidget {
  const _LogsTab({
    required this.logs,
    required this.level,
    required this.scrollController,
    required this.onLevelChanged,
    required this.onClear,
  });

  final List<LogEntry> logs;
  final String level;
  final ScrollController scrollController;
  final ValueChanged<String> onLevelChanged;
  final Future<void> Function() onClear;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 8, 0),
          child: Row(
            children: [
              const Text('Level', style: TextStyle(fontSize: 12)),
              const SizedBox(width: 8),
              DropdownButton<String>(
                value: level,
                isDense: true,
                underline: const SizedBox.shrink(),
                style: const TextStyle(fontSize: 12),
                items: const [
                  DropdownMenuItem(value: 'DEBUG', child: Text('DEBUG')),
                  DropdownMenuItem(value: 'INFO', child: Text('INFO')),
                  DropdownMenuItem(value: 'WARNING', child: Text('WARNING')),
                  DropdownMenuItem(value: 'ERROR', child: Text('ERROR')),
                ],
                onChanged: (value) {
                  if (value != null) onLevelChanged(value);
                },
              ),
              const Spacer(),
              TextButton.icon(
                onPressed: onClear,
                icon: const Icon(Icons.delete_outline, size: 16),
                label: const Text('Clear'),
              ),
            ],
          ),
        ),
        Expanded(
          child: Container(
            width: double.infinity,
            color: const Color(0xFF1E1E1E),
            child: logs.isEmpty
                ? const Center(
                    child: Text(
                      'No logs yet.',
                      style: TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  )
                : ListView.builder(
                    controller: scrollController,
                    padding: const EdgeInsets.all(8),
                    itemCount: logs.length,
                    itemBuilder: (context, index) =>
                        _LogLine(entry: logs[index]),
                  ),
          ),
        ),
      ],
    );
  }
}

class _LogLine extends StatelessWidget {
  const _LogLine({required this.entry});

  final LogEntry entry;

  static const Map<String, Color> _levelColors = {
    'DEBUG': Color(0xFF9E9E9E),
    'INFO': Color(0xFF8AB4F8),
    'WARNING': Color(0xFFFFCC66),
    'ERROR': Color(0xFFFF8A80),
    'CRITICAL': Color(0xFFFF8A80),
  };

  @override
  Widget build(BuildContext context) {
    final color = _levelColors[entry.level] ?? Colors.white70;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: SelectableText.rich(
        TextSpan(
          style: const TextStyle(
              fontFamily: 'monospace', fontSize: 11, color: Colors.white70),
          children: [
            TextSpan(
                text: '${_timeOf(entry.time)} ',
                style: const TextStyle(color: Colors.white38)),
            TextSpan(
                text: '${entry.level.padRight(8)} ',
                style: TextStyle(color: color)),
            TextSpan(
                text: '${entry.logger}: ',
                style: const TextStyle(color: Colors.white54)),
            TextSpan(text: entry.message),
          ],
        ),
      ),
    );
  }
}

/// Formats an ISO-8601 timestamp as local `HH:MM:SS`.
String _timeOf(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  final local = parsed.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return '${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
}
