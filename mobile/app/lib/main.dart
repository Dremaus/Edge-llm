import 'package:flutter/material.dart';

import 'api.dart';
import 'app_lock.dart';
import 'screens/chat.dart';
import 'screens/onboarding.dart';
import 'secure_store.dart';

void main() => runApp(const EdgeApp());

class EdgeApp extends StatefulWidget {
  const EdgeApp({super.key});

  @override
  State<EdgeApp> createState() => _EdgeAppState();
}

class _EdgeAppState extends State<EdgeApp> {
  final _store = SecureStore();
  EdgeApi? _api;
  String _lang = 'pl';
  bool _lockEnabled = true;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final saved = await _store.load();
    final lock = await _store.lockEnabled();
    setState(() {
      if (saved != null) {
        _api = EdgeApi(parseDeviceUrl(saved.url), saved.token);
        _lang = saved.lang;
      }
      _lockEnabled = lock;
      _loading = false;
    });
  }

  Future<void> _unpair() async {
    await _store.clear();
    if (mounted) setState(() => _api = null);
  }

  @override
  Widget build(BuildContext context) {
    final Widget home;
    if (_loading) {
      home = const Scaffold(body: Center(child: CircularProgressIndicator()));
    } else if (_api == null) {
      home = OnboardingScreen(
        store: _store,
        onDone: (api, lang) => setState(() {
          _api = api;
          _lang = lang;
        }),
      );
    } else {
      home = AppLock(
        enabled: _lockEnabled,
        child: ChatScreen(
          api: _api!,
          store: _store,
          lang: _lang,
          onUnpaired: _unpair,
          onLanguageChanged: (lang) => setState(() => _lang = lang),
        ),
      );
    }
    return MaterialApp(
      title: 'edge-llm',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF2F6F5E), useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF2F6F5E),
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: home,
    );
  }
}
