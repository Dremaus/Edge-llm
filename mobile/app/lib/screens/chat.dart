import 'package:flutter/material.dart';

import '../api.dart';
import '../strings.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.api, required this.lang, required this.onUnpaired});

  final EdgeApi api;
  final String lang;
  final VoidCallback onUnpaired;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _messages = <Map<String, dynamic>>[];
  final _input = TextEditingController();
  final _scroll = ScrollController();
  String? _conversationId;
  bool _sending = false;

  S get s => S(widget.lang);

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    _input.clear();
    setState(() {
      _sending = true;
      _messages.add({'role': 'user', 'content': text});
      _messages.add({'role': 'assistant', 'content': ''});
    });
    final history = _messages.sublist(0, _messages.length - 1);
    try {
      await for (final delta in widget.api.chat(
        history,
        conversationId: _conversationId,
        onConversation: (id) => _conversationId = id,
      )) {
        setState(() => _messages.last['content'] = (_messages.last['content'] as String) + delta);
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      }
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
      appBar: AppBar(title: Text(s.t('chat_title'))),
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
                    child: SelectableText(m['content'] as String),
                  ),
                );
              },
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
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
