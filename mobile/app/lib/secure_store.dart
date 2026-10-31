import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Dane dostępu przechowywane wyłącznie w Keystore (Android) / Keychain (iOS).
class SecureStore {
  SecureStore([FlutterSecureStorage? storage])
      : _s = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
            );

  final FlutterSecureStorage _s;

  Future<void> save({required String url, required String token, required String lang}) async {
    await _s.write(key: 'url', value: url);
    await _s.write(key: 'token', value: token);
    await _s.write(key: 'lang', value: lang);
  }

  Future<({String url, String token, String lang})?> load() async {
    final url = await _s.read(key: 'url');
    final token = await _s.read(key: 'token');
    final lang = await _s.read(key: 'lang') ?? 'pl';
    if (url == null || token == null) return null;
    return (url: url, token: token, lang: lang);
  }

  Future<void> setLang(String lang) => _s.write(key: 'lang', value: lang);

  Future<bool> lockEnabled() async => (await _s.read(key: 'app_lock')) != '0';

  Future<void> setLockEnabled(bool on) => _s.write(key: 'app_lock', value: on ? '1' : '0');

  /// Wylogowanie: usuwa token z telefonu.
  Future<void> clear() => _s.deleteAll();
}
