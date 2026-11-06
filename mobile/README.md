# Aplikacja mobilna (Flutter)

Aplikacja na Androida i iOS. Kod źródłowy jest w `mobile/app/` (kreator, parowanie QR, czat ze strumieniowaniem).

> **Stan:** kod napisany bez dostępu do Fluttera — nie był jeszcze kompilowany. Pierwszy krok to `flutter analyze` i `flutter test` (robi to też CI).

Utworzenie katalogów platform (android/, ios/) — jednorazowo:

```bash
cd mobile/app
flutter create --org pl.edgellm --project-name edge_llm_app --platforms android,ios .
flutter pub get
flutter test
```

Uprawnienia do aparatu (skaner QR):
- Android: `android/app/src/main/AndroidManifest.xml` — `<uses-permission android:name="android.permission.CAMERA"/>`
- iOS: `ios/Runner/Info.plist` — klucz `NSCameraUsageDescription`

Mikrofon (rozpoznawanie mowy): Android `<uses-permission android:name="android.permission.RECORD_AUDIO"/>`, iOS klucz `NSMicrophoneUsageDescription`.

Blokada biometryczna (local_auth) na Androidzie wymaga, by `MainActivity` dziedziczyła po `FlutterFragmentActivity`; na iOS dodaj `NSFaceIDUsageDescription` do `Info.plist`. Wybór zdjęć (image_picker) na iOS wymaga `NSPhotoLibraryUsageDescription`.

Zakaz zrzutów ekranu i podglądu w przełączniku aplikacji (Android): w `MainActivity` ustawić `window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)`.

## Zakres MVP

- [x] Kreator pierwszego uruchomienia: wybór języka (Polski / English), parowanie kodem QR, wybór modelu (Qwen3.5-4B domyślnie; przy polskim podpowiedź „Użyj Bielika”)
- [x] Czat ze strumieniowaniem odpowiedzi (SSE z `/v1/chat/completions`, model `auto`)
- [x] Lista rozmów i historia
- [x] Wysyłanie zdjęć do modelu (treść `image_url`)
- [x] Status urządzenia: online/offline, temperatura, pamięć
- [ ] Działanie w sieci domowej i poza nią (Tailscale)

## Wymagania bezpieczeństwa aplikacji

- [x] Token przechowywany wyłącznie w Android Keystore / iOS Keychain (nigdy w SharedPreferences ani w plikach)
- [x] Blokada aplikacji biometrią lub PIN-em; ukrywanie treści na podglądzie ostatnich aplikacji
- [x] Połączenia tylko HTTPS do adresu urządzenia w sieci Tailscale (`*.ts.net`); brak zgody na HTTP i niezaufane certyfikaty
- [x] Historia rozmów przechowywana tylko na urządzeniu (telefon jej nie zapisuje)
- [x] Brak analityki i zewnętrznych SDK śledzących; brak logowania treści rozmów
- [x] Wylogowanie = usunięcie tokenu z telefonu + prośba o unieważnienie na urządzeniu
- [ ] Zrzuty ekranu zablokowane na ekranie z tokenem i kodem QR (FLAG_SECURE)

## Kontrakt z serwerem

- Uwierzytelnianie: nagłówek `Authorization: Bearer <token>` (token per telefon, prefiks `edge_`).
- Obrazy tylko jako `data:image/...;base64` (maks. 4 na zapytanie).
- Odpowiedzi 401 = token nieważny (wróć do parowania); 429 = limit zapytań lub blokada po nieudanych próbach.
- Czat: `POST /v1/chat/completions` (format OpenAI), `"model": "auto"`, `"stream": true`.
- Serwer zwraca wybrany model i ścieżkę w nagłówkach `X-Edge-Model` i `X-Edge-Route`.
