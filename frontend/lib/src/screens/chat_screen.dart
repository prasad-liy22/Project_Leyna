import 'package:flutter/material.dart';

import '../api/chat_backend.dart';
import '../api/debug_api.dart';
import '../models/chat_message.dart';
import '../widgets/message_bubble.dart';
import 'debug_panel.dart';

/// The main chat screen: a scrolling transcript plus a composer.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, this.backend, this.debugBackend});

  /// Injectable for tests; defaults to a real [ChatApi].
  final ChatBackend? backend;

  /// Injectable for tests; defaults to a real [DebugApi].
  final DebugBackend? debugBackend;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late final ChatBackend _backend = widget.backend ?? ChatApi();
  late final DebugBackend _debugBackend = widget.debugBackend ?? DebugApi();
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];

  bool _sending = false;
  bool _showDebug = false;
  HealthStatus? _health;

  @override
  void initState() {
    super.initState();
    _checkHealth();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _checkHealth() async {
    final health = await _backend.health();
    if (!mounted) return;
    setState(() => _health = health);
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;

    setState(() {
      _messages.add(ChatMessage(role: ChatRole.user, text: text));
      _sending = true;
    });
    _controller.clear();
    _scrollToBottom();

    try {
      final reply = await _backend.sendMessage(List.unmodifiable(_messages));
      if (!mounted) return;
      setState(() {
        _messages.add(ChatMessage(role: ChatRole.assistant, text: reply));
      });
    } on ChatApiException catch (error) {
      if (mounted) _showError(error.message);
    } catch (error) {
      if (mounted) _showError('Something went wrong: $error');
    } finally {
      if (mounted) setState(() => _sending = false);
      _scrollToBottom();
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  void _toggleDebug() {
    setState(() => _showDebug = _showDebug != true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Leyna'),
        actions: [
          _StatusIndicator(health: _health),
          const SizedBox(width: 4),
          TextButton.icon(
            onPressed: _toggleDebug,
            icon: const Icon(Icons.bug_report, size: 18),
            label: const Text('Debug'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          AnimatedSize(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOut,
            alignment: Alignment.topCenter,
            child: _showDebug == true
                ? DebugPanel(
                    backend: _debugBackend,
                    onClose: () => setState(() => _showDebug = false),
                    onApiKeyChanged: _checkHealth,
                  )
                : const SizedBox(width: double.infinity),
          ),
          Expanded(child: _buildTranscript()),
          if (_sending) const LinearProgressIndicator(minHeight: 2),
          _buildComposer(context),
        ],
      ),
    );
  }

  Widget _buildTranscript() {
    if (_messages.isEmpty) {
      return const _EmptyState();
    }
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.symmetric(vertical: 12),
      itemCount: _messages.length,
      itemBuilder: (context, index) => MessageBubble(message: _messages[index]),
    );
  }

  Widget _buildComposer(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                enabled: !_sending,
                minLines: 1,
                maxLines: 6,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: const InputDecoration(
                  hintText: 'Ask Leyna anything…',
                  border: OutlineInputBorder(),
                  isDense: true,
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: _sending ? null : _send,
              icon: const Icon(Icons.send),
              tooltip: 'Send',
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.assistant, size: 56, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text('Say hello to Leyna', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              'Your messages are sent to the Leyna backend.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

/// Small coloured dot in the app bar describing connectivity.
class _StatusIndicator extends StatelessWidget {
  const _StatusIndicator({this.health});

  final HealthStatus? health;

  @override
  Widget build(BuildContext context) {
    final (Color color, String label) = switch (health) {
      null => (Colors.grey, 'Checking API…'),
      HealthStatus(reachable: false) => (Colors.red, 'API unreachable'),
      HealthStatus(configured: false) => (Colors.orange, 'API key not set'),
      _ => (Colors.green, 'Connected'),
    };

    return Tooltip(
      message: label,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 8),
            Text(label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
