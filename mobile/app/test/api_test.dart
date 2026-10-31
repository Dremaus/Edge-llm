import 'package:edge_llm_app/api.dart';
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
}
