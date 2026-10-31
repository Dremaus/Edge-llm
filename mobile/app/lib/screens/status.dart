import 'package:flutter/material.dart';

import '../api.dart';
import '../strings.dart';

class StatusScreen extends StatefulWidget {
  const StatusScreen({super.key, required this.api, required this.lang});

  final EdgeApi api;
  final String lang;

  @override
  State<StatusScreen> createState() => _StatusScreenState();
}

class _StatusScreenState extends State<StatusScreen> {
  late Future<Map<String, dynamic>> _status = widget.api.status();

  S get s => S(widget.lang);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(s.t('status'))),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() => _status = widget.api.status());
          await _status;
        },
        child: FutureBuilder<Map<String, dynamic>>(
          future: _status,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [ListTile(title: Text(s.t('offline')))]);
            final st = snap.data;
            if (st == null) return const Center(child: CircularProgressIndicator());
            final mem = (st['memory'] as Map?) ?? const {};
            final disk = (st['disk'] as Map?) ?? const {};
            final temp = st['temperature_c'];
            return ListView(
              children: [
                if (st['temperature_warning'] == true)
                  MaterialBanner(content: Text(s.t('hot')), actions: const [SizedBox.shrink()]),
                ListTile(
                  leading: const Icon(Icons.thermostat),
                  title: Text(s.t('temperature')),
                  trailing: Text(temp == null ? '—' : '$temp °C'),
                ),
                ListTile(
                  leading: const Icon(Icons.memory),
                  title: Text(s.t('memory')),
                  trailing: Text(mem.isEmpty ? '—' : '${mem['available_mb']} / ${mem['total_mb']} MB'),
                ),
                ListTile(
                  leading: const Icon(Icons.storage),
                  title: Text(s.t('disk')),
                  trailing: Text(disk.isEmpty ? '—' : '${disk['free_gb']} / ${disk['total_gb']} GB'),
                ),
                ListTile(
                  leading: const Icon(Icons.smart_toy_outlined),
                  title: Text(s.t('models_loaded')),
                  subtitle: Text(((st['loaded_models'] as List?) ?? const []).join('\n')),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
