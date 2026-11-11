import 'package:flutter/material.dart';

import '../api.dart';
import '../secure_store.dart';
import '../strings.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.api,
    required this.store,
    required this.lang,
    required this.onLanguageChanged,
    required this.onLoggedOut,
  });

  final EdgeApi api;
  final SecureStore store;
  final String lang;
  final void Function(String lang) onLanguageChanged;
  final VoidCallback onLoggedOut;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Map<String, dynamic>? _settings;
  List<dynamic> _devices = const [];
  bool _lock = true;
  late String _lang = widget.lang;

  S get s => S(_lang);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final results = await Future.wait([widget.api.getSettings(), widget.api.devices()]);
    final lock = await widget.store.lockEnabled();
    if (!mounted) return;
    setState(() {
      _settings = results[0] as Map<String, dynamic>;
      _devices = results[1] as List<dynamic>;
      _lock = lock;
    });
  }

  Future<void> _update(Map<String, dynamic> changes) async {
    final updated = await widget.api.updateSettings(changes);
    setState(() => _settings = updated);
    if (changes.containsKey('language')) {
      _lang = changes['language'] as String;
      await widget.store.setLang(_lang);
      widget.onLanguageChanged(_lang);
    }
  }

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(s.t('logout')),
        content: Text(s.t('logout_confirm')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(s.t('cancel'))),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(s.t('logout'))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.unpairSelf();
    } catch (_) {
      // Nawet bez połączenia usuwamy token z telefonu; na urządzeniu można go unieważnić w konsoli.
    }
    await widget.store.clear();
    widget.onLoggedOut();
  }

  @override
  Widget build(BuildContext context) {
    final st = _settings;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('settings'))),
      body: st == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                ListTile(
                  title: Text(s.t('language')),
                  trailing: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'pl', label: Text('PL')),
                      ButtonSegment(value: 'en', label: Text('EN')),
                    ],
                    selected: {st['language'] as String},
                    onSelectionChanged: (v) => _update({'language': v.first}),
                  ),
                ),
                ListTile(
                  title: Text(s.t('model')),
                  trailing: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'qwen', label: Text('Qwen')),
                      ButtonSegment(value: 'bielik', label: Text('Bielik')),
                    ],
                    selected: {st['chat_model'] as String},
                    onSelectionChanged: (v) => _update({'chat_model': v.first}),
                  ),
                ),
                ListTile(
                  title: Text(s.t('thinking')),
                  subtitle: Text(s.t('thinking_hint')),
                  trailing: SegmentedButton<String>(
                    segments: [
                      ButtonSegment(value: 'off', label: Text(s.t('thinking_off'))),
                      ButtonSegment(value: 'short', label: Text(s.t('thinking_short'))),
                      ButtonSegment(value: 'full', label: Text(s.t('thinking_full'))),
                    ],
                    selected: {(st['thinking'] as String?) ?? 'off'},
                    onSelectionChanged: (v) => _update({'thinking': v.first}),
                  ),
                ),
                SwitchListTile(
                  title: Text(s.t('app_lock')),
                  value: _lock,
                  onChanged: (v) async {
                    await widget.store.setLockEnabled(v);
                    setState(() => _lock = v);
                  },
                ),
                const Divider(),
                ListTile(title: Text(s.t('devices'), style: Theme.of(context).textTheme.titleMedium)),
                for (final d in _devices)
                  ListTile(
                    leading: const Icon(Icons.smartphone),
                    title: Text('${d['name']}'),
                    subtitle: Text([
                      if (d['current'] == true) s.t('this_phone'),
                      if (d['revoked'] == true) s.t('revoked'),
                    ].join(' · ')),
                  ),
                const Divider(),
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: OutlinedButton.icon(
                    onPressed: _logout,
                    icon: const Icon(Icons.logout),
                    label: Text(s.t('logout')),
                  ),
                ),
              ],
            ),
    );
  }
}
