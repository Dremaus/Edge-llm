import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../images.dart';
import '../secure_store.dart';
import '../strings.dart';
import 'settings.dart';
import 'status.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.api,
    required this.store,
    required this.lang,
    required this.onUnpaired,
    required this.onLanguageChanged,
  });

  final EdgeApi api;
  final SecureStore store;
  final String lang;
  final VoidCallback onUnpaired;
  final void Function(String lang) onLanguageChanged;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _messages = <Map<String, dynamic>>[];
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _picker = ImagePicker();
  final _pendingImages = <String>[];
  List<dynamic> _conversations = const [];
  String? _conversationId;
  bool _sending = false;

  S get s => S(widget.lang);

  @override
  void initState() {
    super.initState();
    _refreshConversations();
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _refreshConversations() async {
    try {
      final list = await widget.api.conversations();
      if (mounted) setState(() => _conversations = list);
    } on ApiException catch (e) {
      if (e.unauthorized) widget.onUnpaired();
    } catch (_) {}
  }

  Future<void> _openConversation(String id) async {
    Navigator.of(context).pop(); // zamknij szufladę
    try {
      final conv = await widget.api.conversation(id);
      setState(() {
        _conversationId = id;
        _messages
          ..clear()
          ..addAll([
            for (final m in conv['messages'] as List)
              {'role': m['role'], 'content': displayText(m['content'])},
          ]);
      });
    } catch (_) {
      _showError(s.t('error'));
    }
  }

  void _newConversation() {
    Navigator.of(context).maybePop();
    setState(() {
      _conversationId = null;
      _messages.clear();
      _pendingImages.clear();
    });
  }

  Future<void> _deleteConversation(String id) async {
    await widget.api.deleteConversation(id);
    if (_conversationId == id) _newConversation();
    await _refreshConversations();
  }

  Future<void> _pickImage() async {
    if (_pendingImages.length >= maxImagesPerMessage) return;
    // Zmniejszamy zdjęcie już na telefonie: szybszy transfer i mniej tokenów dla modelu.
    final file = await _picker.pickImage(source: ImageSource.gallery, maxWidth: 1280, imageQuality: 80);
    if (file == null) return;
    try {
      final url = toDataUrl(await file.readAsBytes());
      setState(() => _pendingImages.add(url));
    } on ArgumentError {
      _showError(s.t('error'));
    }
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if ((text.isEmpty && _pendingImages.isEmpty) || _sending) return;
    final content = buildContent(text, List.of(_pendingImages));
    _input.clear();
    setState(() {
      _sending = true;
      _pendingImages.clear();
      _messages.add({'role': 'user', 'content': content});
      _messages.add({'role': 'assistant', 'content': ''});
    });
    // Do modelu wysyłamy pełną treść; obrazy są tylko w bieżącej wiadomości.
    final history = [
      for (var i = 0; i < _messages.length - 1; i++)
        {
          'role': _messages[i]['role'],
          'content': i == _messages.length - 2 ? _messages[i]['content'] : displayText(_messages[i]['content']),
        },
    ];
    final isNew = _conversationId == null;
    try {
      await for (final delta in widget.api.chat(
        history,
        conversationId: _conversationId,
        onConversation: (id) => _conversationId = id,
      )) {
        setState(() => _messages.last['content'] = (_messages.last['content'] as String) + delta);
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      }
      if (isNew) _refreshConversations();
    } on ApiException catch (e) {
      if (e.unauthorized) {
        widget.onUnpaired();
        return;
      }
      _showError(e.tooManyRequests ? s.t('too_many') : s.t('error'));
    } catch (_) {
      _showError(s.t('offline'));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    setState(() {
      if (_messages.isNotEmpty && _messages.last['content'] == '') _messages.removeLast();
    });
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('chat_title')),
        actions: [
          IconButton(
            tooltip: s.t('status'),
            icon: const Icon(Icons.monitor_heart_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => StatusScreen(api: widget.api, lang: widget.lang)),
            ),
          ),
          IconButton(
            tooltip: s.t('settings'),
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SettingsScreen(
                  api: widget.api,
                  store: widget.store,
                  lang: widget.lang,
                  onLanguageChanged: widget.onLanguageChanged,
                  onLoggedOut: () {
                    Navigator.of(context).popUntil((r) => r.isFirst);
                    widget.onUnpaired();
                  },
                ),
              ),
            ),
          ),
        ],
      ),
      drawer: Drawer(
        child: SafeArea(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.add),
                title: Text(s.t('new_chat')),
                onTap: _newConversation,
              ),
              const Divider(),
              Expanded(
                child: ListView(
                  children: [
                    for (final c in _conversations)
                      ListTile(
                        title: Text('${c['title']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                        selected: c['id'] == _conversationId,
                        onTap: () => _openConversation(c['id'] as String),
                        trailing: IconButton(
                          tooltip: s.t('delete'),
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () => _deleteConversation(c['id'] as String),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              itemCount: _messages.length,
              itemBuilder: (_, i) {
                final m = _messages[i];
                final mine = m['role'] == 'user';
                return Align(
                  alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(12),
                    constraints: const BoxConstraints(maxWidth: 320),
                    decoration: BoxDecoration(
                      color: mine ? scheme.primaryContainer : scheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: SelectableText(displayText(m['content'])),
                  ),
                );
              },
            ),
          ),
          if (_pendingImages.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Row(
                children: [
                  for (var i = 0; i < _pendingImages.length; i++)
                    InputChip(
                      label: Text('🖼 ${i + 1}'),
                      onDeleted: () => setState(() => _pendingImages.removeAt(i)),
                    ),
                ],
              ),
            ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
                  IconButton(
                    tooltip: s.t('photo'),
                    onPressed: _sending ? null : _pickImage,
                    icon: const Icon(Icons.add_photo_alternate_outlined),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 5,
                      decoration: InputDecoration(hintText: s.t('input_hint')),
                      onSubmitted: (_) => _send(),
                    ),
                  ),
                  IconButton(onPressed: _sending ? null : _send, icon: const Icon(Icons.send)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
