import 'dart:typed_data';

import 'package:edge_llm_app/images.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('text only stays a string', () {
    expect(buildContent('hej', []), 'hej');
  });

  test('text with images becomes OpenAI parts', () {
    final content = buildContent('co to?', ['data:image/jpeg;base64,AA==']) as List;
    expect(content.first, {'type': 'text', 'text': 'co to?'});
    expect((content.last as Map)['type'], 'image_url');
  });

  test('too many images rejected', () {
    expect(() => buildContent('', List.filled(5, 'data:image/jpeg;base64,AA==')), throwsArgumentError);
  });

  test('data url and size limit', () {
    expect(toDataUrl(Uint8List.fromList([1, 2, 3])), 'data:image/jpeg;base64,AQID');
    expect(() => toDataUrl(Uint8List(maxImageBytes + 1)), throwsArgumentError);
  });

  test('display text hides images', () {
    expect(displayText([{'type': 'text', 'text': 'a'}, {'type': 'image_omitted'}]), 'a 🖼');
    expect(displayText(null), '');
  });
}
