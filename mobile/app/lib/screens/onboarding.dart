import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../secure_store.dart';
import '../strings.dart';

/// Kreator pierwszego uruchomienia: język → parowanie (QR lub kod) → wybór modelu.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key, required this.store, required this.onDone});

  final SecureStore store;
  final void Function(EdgeApi api, String lang) onDone;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  int _step = 0;
  String _lang = 'pl';
  String _chatModel = 'qwen';
  final _url = TextEditingController();
  final _code = TextEditingController();
  EdgeApi? _api;
  String? _error;
  bool _busy = false;

  S get s => S(_lang);

  @override
  void dispose() {
    _url.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final base = parseDeviceUrl(_url.text);
      final paired = await EdgeApi.pair(base, _code.text, 'Telefon');
      await widget.store.save(url: base.toString(), token: paired.token, lang: _lang);
      _api = EdgeApi(base, paired.token);
      setState(() => _step = 2);
    } on FormatException {
      setState(() => _error = s.t('https_only'));
    } on ApiException catch (e) {
      setState(() => _error = e.tooManyRequests ? s.t('too_many') : s.t('error'));
    } catch (_) {
      setState(() => _error = s.t('offline'));
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _scan() async {
    final raw = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const _QrScanPage()),
    );
    final data = raw == null ? null : parsePairingQr(raw);
    if (data != null) {
      _url.text = data.url;
      _code.text = data.code;
      await _connect();
    }
  }

  Future<void> _finish() async {
    final api = _api!;
    setState(() => _busy = true);
    try {
      await api.updateSettings({'language': _lang, 'chat_model': _chatModel, 'onboarding_done': true});
      widget.onDone(api, _lang);
    } catch (_) {
      setState(() => _error = s.t('error'));
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = switch (_step) {
      0 => _languageStep(),
      1 => _pairStep(),
      _ => _modelStep(),
    };
    return Scaffold(
      body: SafeArea(child: Padding(padding: const EdgeInsets.all(24), child: body)),
    );
  }

  Widget _languageStep() => Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.t('welcome'), style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 24),
          for (final (code, label) in [('pl', 'Polski'), ('en', 'English')])
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: FilledButton.tonal(
                onPressed: () => setState(() {
                  _lang = code;
                  _step = 1;
                }),
                child: Text(label),
              ),
            ),
        ],
      );

  Widget _pairStep() => ListView(
        children: [
          Text(s.t('pair_title'), style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text(s.t('pair_hint')),
          const SizedBox(height: 24),
          FilledButton.icon(onPressed: _busy ? null : _scan, icon: const Icon(Icons.qr_code_scanner), label: Text(s.t('scan'))),
          const SizedBox(height: 24),
          TextField(controller: _url, decoration: InputDecoration(labelText: s.t('url')), keyboardType: TextInputType.url),
          TextField(controller: _code, decoration: InputDecoration(labelText: s.t('code')), autocorrect: false),
          const SizedBox(height: 16),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          OutlinedButton(onPressed: _busy ? null : _connect, child: Text(s.t('connect'))),
        ],
      );

  Widget _modelStep() => ListView(
        children: [
          Text(s.t('model_title'), style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          RadioListTile(
            value: 'qwen',
            groupValue: _chatModel,
            onChanged: (v) => setState(() => _chatModel = v!),
            title: Text(s.t('model_qwen')),
          ),
          // Bielik proponujemy przy polskim, ale jest dostępny niezależnie od języka.
          RadioListTile(
            value: 'bielik',
            groupValue: _chatModel,
            onChanged: (v) => setState(() => _chatModel = v!),
            title: Text(s.t('model_bielik')),
            subtitle: Text(s.t('model_bielik_note')),
          ),
          const SizedBox(height: 16),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          FilledButton(onPressed: _busy ? null : _finish, child: Text(s.t('start'))),
        ],
      );
}

class _QrScanPage extends StatefulWidget {
  const _QrScanPage();

  @override
  State<_QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<_QrScanPage> {
  bool _done = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(),
      body: MobileScanner(
        onDetect: (capture) {
          final value = capture.barcodes.firstOrNull?.rawValue;
          if (!_done && value != null) {
            _done = true;
            Navigator.of(context).pop(value);
          }
        },
      ),
    );
  }
}
