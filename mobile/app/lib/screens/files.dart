import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../strings.dart';

/// „Moje pliki”: dokumenty, które asystent może czytać w trybie narzędzi.
class FilesScreen extends StatefulWidget {
  const FilesScreen({super.key, required this.api, required this.lang});

  final EdgeApi api;
  final String lang;

  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  late Future<List<dynamic>> _items = widget.api.files();
  bool _busy = false;

  S get s => S(widget.lang);

  void _reload() => setState(() => _items = widget.api.files());

  Future<void> _add() async {
    final picked = await FilePicker.platform.pickFiles(withData: true);
    final file = picked?.files.single;
    final bytes = file?.bytes;
    if (file == null || bytes == null) return;
    setState(() => _busy = true);
    try {
      await widget.api.uploadFile(file.name, bytes);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s.t('upload_failed'))));
      }
    }
    if (!mounted) return;
    setState(() => _busy = false);
    _reload();
  }

  Future<void> _delete(String name) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(s.t('files_delete')),
        content: Text(name),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(s.t('cancel'))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: Text(s.t('delete'))),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.deleteFile(name);
    if (mounted) _reload();
  }

  String _size(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} kB';
    return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(s.t('files_title'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _busy ? null : _add,
        icon: _busy
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
            : const Icon(Icons.upload_file),
        label: Text(s.t('files_add')),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          _reload();
          await _items;
        },
        child: FutureBuilder<List<dynamic>>(
          future: _items,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [ListTile(title: Text(s.t('offline')))]);
            final items = snap.data;
            if (items == null) return const Center(child: CircularProgressIndicator());
            if (items.isEmpty) return ListView(children: [ListTile(title: Text(s.t('files_empty')))]);
            return ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final f = items[i] as Map<String, dynamic>;
                return ListTile(
                  leading: const Icon(Icons.description_outlined),
                  title: Text('${f['name']}'),
                  subtitle: Text(_size(f['size'] as int)),
                  trailing: IconButton(
                    tooltip: s.t('delete'),
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => _delete(f['name'] as String),
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
