/// Build-time configuration.
///
/// Override the backend URL when running, for example:
///
///   flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
///
/// On an Android emulator the host machine is reachable at `10.0.2.2`:
///
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
class AppConfig {
  const AppConfig._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );
}
