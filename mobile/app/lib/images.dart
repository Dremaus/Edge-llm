import 'dart:convert';
import 'dart:typed_data';

/// Serwer przyjmuje obrazy tylko inline (data:image/...;base64), maks. 4 na zapytanie
/// i ok. 6 MB po zakodowaniu. Zdjęcia zmniejszamy przy wyborze (image_picker: maxWidth/quality).
const maxImagesPerMessage = 4;
const maxImageBytes = 4 * 1024 * 1024;

String toDataUrl(Uint8List bytes, {String mime = 'image/jpeg'}) {
  if (bytes.length > maxImageBytes) {
    throw ArgumentError('Zdjęcie jest zbyt duże');
  }
  return 'data:$mime;base64,${base64Encode(bytes)}';
}

/// Treść wiadomości w formacie OpenAI: sam tekst albo tekst + obrazy.
Object buildContent(String text, List<String> imageDataUrls) {
  if (imageDataUrls.isEmpty) return text;
  if (imageDataUrls.length > maxImagesPerMessage) {
    throw ArgumentError('Maksymalnie $maxImagesPerMessage zdjęcia');
  }
  return [
    if (text.isNotEmpty) {'type': 'text', 'text': text},
    for (final url in imageDataUrls) {'type': 'image_url', 'image_url': {'url': url}},
  ];
}

/// Tekst do wyświetlenia w dymku (obrazy jako znacznik).
String displayText(Object? content) {
  if (content is String) return content;
  if (content is List) {
    final parts = <String>[];
    for (final p in content) {
      if (p is Map && p['type'] == 'text') parts.add('${p['text']}');
      if (p is Map && (p['type'] == 'image_url' || p['type'] == 'image_omitted')) parts.add('🖼');
    }
    return parts.join(' ');
  }
  return '';
}
