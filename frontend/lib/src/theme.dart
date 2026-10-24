import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Seed colour shared by both schemes, so light and dark stay recognisably Nimna.
const Color _seed = Color(0xFF6750A4);

ThemeData _buildTheme(Brightness brightness) => ThemeData(
      useMaterial3: true,
      colorSchemeSeed: _seed,
      brightness: brightness,
    );

/// The light and dark themes. Built once and reused across rebuilds.
final ThemeData leynaLightTheme = _buildTheme(Brightness.light);
final ThemeData leynaDarkTheme = _buildTheme(Brightness.dark);

/// Remembers whether the user prefers light or dark.
///
/// The value starts as [ThemeMode.system] so the app follows the OS until the
/// user makes an explicit choice, which is then persisted. Storage failures
/// (for example in a widget test with no plugin) are ignored, so the app still
/// works with an in-memory preference.
class ThemeController extends ValueNotifier<ThemeMode> {
  ThemeController() : super(ThemeMode.system);

  /// Key used in `shared_preferences`.
  static const String preferenceKey = 'leyna.theme';

  /// Restores a previously saved choice, if there is one.
  Future<void> load() async {
    final saved = await _read();
    if (saved == 'light') {
      value = ThemeMode.light;
    } else if (saved == 'dark') {
      value = ThemeMode.dark;
    }
  }

  /// Switches to the opposite of [current] and persists the result.
  Future<void> toggle(Brightness current) =>
      setMode(current == Brightness.dark ? ThemeMode.light : ThemeMode.dark);

  Future<void> setMode(ThemeMode mode) async {
    value = mode;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        preferenceKey,
        mode == ThemeMode.dark ? 'dark' : 'light',
      );
    } catch (_) {
      // Storage unavailable — the choice just won't survive a restart.
    }
  }

  Future<String?> _read() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getString(preferenceKey);
    } catch (_) {
      return null;
    }
  }
}
