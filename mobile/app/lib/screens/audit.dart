import 'package:flutter/material.dart';

import '../api.dart';
import '../strings.dart';

/// „Dziennik działań”: co asystent zrobił narzędziami i co zablokowano (tylko podgląd).
class AuditScreen extends StatefulWidget {
  const AuditScreen({super.key, required this.api, required this.lang});

  final EdgeApi api;
  final String lang;

  @override
  State<AuditScreen> createState() => _AuditScreenState();
}

class _AuditScreenState extends State<AuditScreen> {
  late Future<List<dynamic>> _items = widget.api.audit();

  S get s => S(widget.lang);

  String _label(Map<String, dynamic> e) {
    if (e['ok'] == false) return s.t('audit_failed');
    return s.t('audit_${e['decision']}');
  }

  IconData _icon(Map<String, dynamic> e) {
    if (e['ok'] == false) return Icons.error_outline;
    switch (e['decision']) {
      case 'deny':
        return Icons.block;
      case 'rejected':
        return Icons.thumb_down_alt_outlined;
      case 'confirm_requested':
        return Icons.help_outline;
      default:
        return Icons.check_circle_outline;
    }
  }

  String _time(dynamic ts) {
    final d = DateTime.fromMillisecondsSinceEpoch(((ts as num) * 1000).round());
    String two(int n) => n.toString().padLeft(2, '0');
    return '${d.year}-${two(d.month)}-${two(d.day)} ${two(d.hour)}:${two(d.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(s.t('audit_title'))),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() => _items = widget.api.audit());
          await _items;
        },
        child: FutureBuilder<List<dynamic>>(
          future: _items,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [ListTile(title: Text(s.t('offline')))]);
            final items = snap.data;
            if (items == null) return const Center(child: CircularProgressIndicator());
            if (items.isEmpty) return ListView(children: [ListTile(title: Text(s.t('audit_empty')))]);
            return ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final e = items[i] as Map<String, dynamic>;
                final args = '${e['args'] ?? ''}';
                final reason = '${e['reason'] ?? ''}';
                return ListTile(
                  leading: Icon(_icon(e)),
                  title: Text('${e['tool']} — ${_label(e)}'),
                  subtitle: Text([
                    _time(e['ts']),
                    if (reason.isNotEmpty) reason,
                    if (args.isNotEmpty) args,
                  ].join('\n')),
                  isThreeLine: reason.isNotEmpty || args.isNotEmpty,
                );
              },
            );
          },
        ),
      ),
    );
  }
}
