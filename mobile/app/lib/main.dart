import 'package:flutter/material.dart';

import 'api.dart';
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
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final saved = await _store.load();
    setState(() {
      if (saved != null) {
        _api = EdgeApi(parseDeviceUrl(saved.url), saved.token);
        _lang = saved.lang;
      }
      _loading = false;
    });
  }

  Future<void> _unpair() async {
    await _store.clear();
    setState(() => _api = null);
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
      home = ChatScreen(api: _api!, lang: _lang, onUnpaired: _unpair);
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
