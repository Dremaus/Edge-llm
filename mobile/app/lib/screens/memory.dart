import 'package:flutter/material.dart';

import '../api.dart';
import '../strings.dart';

/// „Co pamiętam”: notatki zapisane przez asystenta. Użytkownik widzi je i może usunąć.
class MemoryScreen extends StatefulWidget {
  const MemoryScreen({super.key, required this.api, required this.lang});

  final EdgeApi api;
  final String lang;

  @override
  State<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<MemoryScreen> {
  late Future<List<dynamic>> _items = widget.api.memory();

  S get s => S(widget.lang);

  Future<void> _delete(int id) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(s.t('memory_delete')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(s.t('cancel'))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: Text(s.t('delete'))),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.deleteMemory(id);
    if (!mounted) return;
    setState(() => _items = widget.api.memory());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(s.t('memory_title'))),
      body: RefreshIndicator(
        onRefresh: () async {
          setState(() => _items = widget.api.memory());
          await _items;
        },
        child: FutureBuilder<List<dynamic>>(
          future: _items,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [ListTile(title: Text(s.t('offline')))]);
            final items = snap.data;
            if (items == null) return const Center(child: CircularProgressIndicator());
            if (items.isEmpty) return ListView(children: [ListTile(title: Text(s.t('memory_empty')))]);
            return ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final n = items[i] as Map<String, dynamic>;
                return ListTile(
                  title: Text('${n['text']}'),
                  trailing: IconButton(
                    tooltip: s.t('delete'),
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => _delete(n['id'] as int),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
