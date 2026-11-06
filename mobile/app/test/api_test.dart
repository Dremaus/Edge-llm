import 'dart:convert';

import 'package:edge_llm_app/api.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('parseDeviceUrl', () {
    test('accepts https and strips path', () {
      expect(parseDeviceUrl('https://dom.tail1234.ts.net/x?y=1').toString(), 'https://dom.tail1234.ts.net');
    });
    test('rejects http and garbage', () {
      expect(() => parseDeviceUrl('http://192.168.1.10:8080'), throwsFormatException);
      expect(() => parseDeviceUrl('nie-adres'), throwsFormatException);
    });
  });

  group('parsePairingQr', () {
    test('reads valid payload', () {
      final r = parsePairingQr('{"v":1,"url":"https://a.ts.net","code":"ABCD-EFGH-IJ"}');
      expect(r?.code, 'ABCD-EFGH-IJ');
      expect(r?.url, 'https://a.ts.net');
    });
    test('rejects other payloads', () {
      expect(parsePairingQr('https://phishing.example'), isNull);
      expect(parsePairingQr('{"v":2,"url":"x","code":"y"}'), isNull);
    });
  });

  test('SseDeltaParser joins split chunks', () {
    final p = SseDeltaParser();
    final out = <String>[
      ...p.feed('data: {"choices":[{"delta":{"content":"Cze"}}]}\n\ndata: {"choi'),
      ...p.feed('ces":[{"delta":{"content":"ść"}}]}\n\ndata: [DONE]\n\n'),
    ];
    expect(out.join(), 'Cześć');
  });

  test('agent confirmation posts approve flag to the action URL', () async {
    late http.Request seen;
    final api = EdgeApi(Uri.parse('https://edge.example.ts.net'), 'tok', client: MockClient((req) async {
      seen = req;
      return http.Response(jsonEncode({'status': 'done', 'content': 'ok', 'steps': []}), 200);
    }));
    final out = await api.confirmAction('a/b', true);
    expect(out['content'], 'ok');
    expect(seen.url.path, '/v1/agent/actions/a%2Fb');
    expect(jsonDecode(seen.body), {'approve': true});
    expect(seen.headers['Authorization'], 'Bearer tok');
  });

  test('deleteMemory wysyła DELETE /v1/memory/{id}', () async {
    late http.Request seen;
    final api = EdgeApi(Uri.parse('https://x'), 'tok', client: MockClient((req) async {
      seen = req;
      return http.Response(jsonEncode({'deleted': 7}), 200);
    }));
    await api.deleteMemory(7);
    expect(seen.method, 'DELETE');
    expect(seen.url.path, '/v1/memory/7');
  });

  test('uploadFile wysyła surowe bajty z nazwą w zapytaniu', () async {
    late http.Request seen;
    final api = EdgeApi(Uri.parse('https://x'), 'tok', client: MockClient((req) async {
      seen = req;
      return http.Response(jsonEncode({'name': 'raport (2).pdf'}), 200);
    }));
    final saved = await api.uploadFile('raport.pdf', [1, 2, 3]);
    expect(saved, 'raport (2).pdf');
    expect(seen.method, 'POST');
    expect(seen.url.path, '/v1/files');
    expect(seen.url.queryParameters['name'], 'raport.pdf');
    expect(seen.bodyBytes, [1, 2, 3]);
    expect(seen.headers['Authorization'], 'Bearer tok');
  });

  test('uploadFile zgłasza błąd serwera', () async {
    final api = EdgeApi(Uri.parse('https://x'), 'tok',
        client: MockClient((req) async => http.Response('{"detail":"x"}', 400)));
    expect(() => api.uploadFile('a.txt', [1]), throwsA(isA<ApiException>()));
  });

  test('transcribe wysyła bajty i zwraca przycięty tekst', () async {
    late http.Request seen;
    final api = EdgeApi(Uri.parse('https://x'), 'tok', client: MockClient((req) async {
      seen = req;
      return http.Response(jsonEncode({'text': ' dzień dobry '}), 200);
    }));
    expect(await api.transcribe([9, 8, 7]), 'dzień dobry');
    expect(seen.url.path, '/v1/audio/transcriptions');
    expect(seen.bodyBytes, [9, 8, 7]);
  });

  test('transcribe zgłasza 503, gdy mowa wyłączona', () async {
    final api = EdgeApi(Uri.parse('https://x'), 'tok',
        client: MockClient((req) async => http.Response('{"error":"x"}', 503)));
    expect(() => api.transcribe([1]), throwsA(isA<ApiException>()));
  });
}
