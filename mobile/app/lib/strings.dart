/// Teksty interfejsu w dwóch językach wybieranych w kreatorze.
class S {
  S(this.lang);
  final String lang;

  static const _pl = {
    'welcome': 'Witaj! Wybierz język',
    'pair_title': 'Połącz z urządzeniem',
    'pair_hint': 'Zeskanuj kod QR wyświetlony na urządzeniu albo wpisz kod ręcznie.',
    'scan': 'Zeskanuj kod QR',
    'url': 'Adres urządzenia (https://...ts.net)',
    'code': 'Kod parowania',
    'connect': 'Połącz',
    'model_title': 'Wybierz model',
    'model_qwen': 'Qwen3.5-4B — polski i angielski, rozumie zdjęcia (zalecany)',
    'model_bielik': 'Bielik 4.5B — specjalizowany w języku polskim',
    'model_bielik_note': 'Zdjęcia nadal analizuje Qwen — Bielik ich nie obsługuje.',
    'start': 'Zaczynamy',
    'chat_title': 'Asystent',
    'input_hint': 'Napisz wiadomość…',
    'offline': 'Brak połączenia z urządzeniem',
    'unauthorized': 'Telefon nie jest już sparowany. Połącz ponownie.',
    'too_many': 'Zbyt wiele zapytań. Spróbuj za chwilę.',
    'https_only': 'Dozwolone są tylko adresy https://',
    'error': 'Coś poszło nie tak',
  };

  static const _en = {
    'welcome': 'Welcome! Choose your language',
    'pair_title': 'Connect to your device',
    'pair_hint': 'Scan the QR code shown on the device or enter the code manually.',
    'scan': 'Scan QR code',
    'url': 'Device address (https://...ts.net)',
    'code': 'Pairing code',
    'connect': 'Connect',
    'model_title': 'Choose a model',
    'model_qwen': 'Qwen3.5-4B — Polish and English, understands photos (recommended)',
    'model_bielik': 'Bielik 4.5B — specialised in Polish',
    'model_bielik_note': 'Photos are still handled by Qwen — Bielik does not support them.',
    'start': "Let's start",
    'chat_title': 'Assistant',
    'input_hint': 'Type a message…',
    'offline': 'Cannot reach the device',
    'unauthorized': 'This phone is no longer paired. Please reconnect.',
    'too_many': 'Too many requests. Try again shortly.',
    'https_only': 'Only https:// addresses are allowed',
    'error': 'Something went wrong',
  };

  String t(String key) => (lang == 'pl' ? _pl : _en)[key] ?? key;
}
