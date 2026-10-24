import 'package:flutter/material.dart';

import 'src/api/chat_backend.dart';
import 'src/api/debug_api.dart';
import 'src/screens/chat_screen.dart';
import 'src/theme.dart';

void main() {
  runApp(const NimnaApp());
}

/// The application root: wires the theme controller into [MaterialApp] so the
/// light/dark preference is applied everywhere.
class NimnaApp extends StatefulWidget {
  const NimnaApp({
    super.key,
    this.backend,
    this.debugBackend,
    this.themeController,
  });

  /// Injectable for tests; defaults to a real [ChatApi].
  final ChatBackend? backend;

  /// Injectable for tests; defaults to a real [DebugApi].
  final DebugBackend? debugBackend;

  /// Injectable for tests; one is created (and disposed) when omitted.
  final ThemeController? themeController;

  @override
  State<NimnaApp> createState() => _NimnaAppState();
}

class _NimnaAppState extends State<NimnaApp> {
  late final ThemeController _theme;
  late final bool _ownsTheme;

  @override
  void initState() {
    super.initState();
    _theme = widget.themeController ?? ThemeController();
    _ownsTheme = widget.themeController == null;
    // Follows the OS until a saved choice arrives.
    _theme.load();
  }

  @override
  void dispose() {
    if (_ownsTheme) _theme.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: _theme,
      builder: (context, mode, _) => MaterialApp(
        title: 'Nimna Assistant',
        debugShowCheckedModeBanner: false,
        theme: leynaLightTheme,
        darkTheme: leynaDarkTheme,
        themeMode: mode,
        home: ChatScreen(
          backend: widget.backend,
          debugBackend: widget.debugBackend,
          themeController: _theme,
        ),
      ),
    );
  }
}
