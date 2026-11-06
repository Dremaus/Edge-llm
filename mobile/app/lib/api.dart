import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.status, [this.message = '']);
  final int status;
  final String message;

  bool get unauthorized => status == 401;
  bool get tooManyRequests => status == 429;

  @override
  String toString() => 'ApiException($status, $message)';
}

/// Akceptujemy wyłącznie HTTPS (adres urządzenia w sieci Tailscale).
Uri parseDeviceUrl(String raw) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
    throw const FormatException('https_only');
  }
  return Uri(scheme: 'https', host: uri.host, port: uri.hasPort ? uri.port : null);
}

/// Treść kodu QR: {"v":1,"url":"https://...","code":"XXXX-XXXX-XX"}
({String url, String code})? parsePairingQr(String raw) {
  try {
    final data = jsonDecode(raw);
    if (data is Map && data['v'] == 1 && data['url'] is String && data['code'] is String) {
      return (url: data['url'] as String, code: data['code'] as String);
    }
  } on FormatException {
    return null;
  }
  return null;
}

/// Wyciąga tekst z kolejnych zdarzeń SSE (format OpenAI); bufor obsługuje linie przecięte między paczkami.
class SseDeltaParser {
  String _buffer = '';

  List<String> feed(String chunk) {
    _buffer += chunk;
    final out = <String>[];
    while (_buffer.contains('\n')) {
      final idx = _buffer.indexOf('\n');
      final line = _buffer.substring(0, idx).trim();
      _buffer = _buffer.substring(idx + 1);
      if (!line.startsWith('data:')) continue;
      final data = line.substring(5).trim();
      if (data.isEmpty || data == '[DONE]') continue;
      try {
        final event = jsonDecode(data);
        final delta = event['choices']?[0]?['delta']?['content'];
        if (delta is String) out.add(delta);
      } on FormatException {
        continue;
      }
    }
    return out;
  }
}

class EdgeApi {
  EdgeApi(this.baseUrl, this.token, {http.Client? client}) : _client = client ?? http.Client();

  final Uri baseUrl;
  final String token;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  static Future<({String deviceId, String token})> pair(
    Uri baseUrl,
    String code,
    String deviceName, {
    http.Client? client,
  }) async {
    final c = client ?? http.Client();
    final res = await c.post(
      baseUrl.resolve('/v1/pair'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'code': code, 'device_name': deviceName}),
    );
    if (res.statusCode != 200) throw ApiException(res.statusCode);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    return (deviceId: body['device_id'] as String, token: body['token'] as String);
  }

  Future<Map<String, dynamic>> getSettings() => _json('GET', '/v1/settings');

  Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> changes) =>
      _json('PATCH', '/v1/settings', changes);

  Future<Map<String, dynamic>> status() => _json('GET', '/v1/status');

  Future<List<dynamic>> conversations() async =>
      (await _json('GET', '/v1/conversations'))['data'] as List<dynamic>;

  Future<Map<String, dynamic>> conversation(String id) =>
      _json('GET', '/v1/conversations/${Uri.encodeComponent(id)}');

  Future<void> deleteConversation(String id) =>
      _json('DELETE', '/v1/conversations/${Uri.encodeComponent(id)}');

  /// Pamięć agenta (notatki) — użytkownik może ją przejrzeć i usunąć wpis.
  Future<List<dynamic>> memory() async => (await _json('GET', '/v1/memory'))['data'] as List<dynamic>;

  Future<void> deleteMemory(int id) => _json('DELETE', '/v1/memory/$id');

  /// Pliki użytkownika dla narzędzi agenta (PDF, arkusze, tekst).
  Future<List<dynamic>> files() async => (await _json('GET', '/v1/files'))['data'] as List<dynamic>;

  /// Wysyła plik; serwer może zmienić nazwę (np. „raport (2).pdf”) i zwraca zapisaną.
  Future<String> uploadFile(String name, List<int> bytes) async {
    final res = await _client.post(
      baseUrl.resolve('/v1/files').replace(queryParameters: {'name': name}),
      headers: {'Authorization': 'Bearer $token', 'Content-Type': 'application/octet-stream'},
      body: bytes,
    );
    if (res.statusCode != 200) throw ApiException(res.statusCode);
    return (jsonDecode(res.body) as Map<String, dynamic>)['name'] as String;
  }

  Future<void> deleteFile(String name) => _json('DELETE', '/v1/files/${Uri.encodeComponent(name)}');

  /// Mowa na tekst (whisper.cpp na urządzeniu). Wysyła surowe bajty nagrania (WAV).
  Future<String> transcribe(List<int> audio) async {
    final res = await _client.post(
      baseUrl.resolve('/v1/audio/transcriptions'),
      headers: {'Authorization': 'Bearer $token', 'Content-Type': 'application/octet-stream'},
      body: audio,
    );
    if (res.statusCode != 200) throw ApiException(res.statusCode);
    return ((jsonDecode(res.body) as Map<String, dynamic>)['text'] as String? ?? '').trim();
  }

  Future<List<dynamic>> devices() async => (await _json('GET', '/v1/devices'))['data'] as List<dynamic>;

  /// Zadanie z narzędziami. Wynik: status `done` z `content` albo `needs_confirmation` z `action`.
  Future<Map<String, dynamic>> agent(List<Map<String, dynamic>> messages) =>
      _json('POST', '/v1/agent', {'messages': messages});

  Future<Map<String, dynamic>> confirmAction(String id, bool approve) =>
      _json('POST', '/v1/agent/actions/${Uri.encodeComponent(id)}', {'approve': approve});

  /// Wylogowanie: unieważnia token tego telefonu na urządzeniu.
  Future<void> unpairSelf() => _json('DELETE', '/v1/devices/me');

  /// Strumień fragmentów odpowiedzi. `onConversation` dostaje id rozmowy z nagłówka.
  Stream<String> chat(
    List<Map<String, dynamic>> messages, {
    String? conversationId,
    void Function(String id)? onConversation,
  }) async* {
    final req = http.Request('POST', baseUrl.resolve('/v1/chat/completions'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({
        'model': 'auto',
        'stream': true,
        'messages': messages,
        if (conversationId != null) 'conversation_id': conversationId else 'save': true,
      });
    final res = await _client.send(req);
    if (res.statusCode != 200) {
      throw ApiException(res.statusCode);
    }
    final conv = res.headers['x-edge-conversation'];
    if (conv != null && onConversation != null) onConversation(conv);
    final parser = SseDeltaParser();
    await for (final chunk in res.stream.transform(utf8.decoder)) {
      for (final delta in parser.feed(chunk)) {
        yield delta;
      }
    }
  }

  Future<Map<String, dynamic>> _json(String method, String path, [Object? body]) async {
    final req = http.Request(method, baseUrl.resolve(path))..headers.addAll(_headers);
    if (body != null) req.body = jsonEncode(body);
    final res = await http.Response.fromStream(await _client.send(req));
    if (res.statusCode != 200) throw ApiException(res.statusCode);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }
}
