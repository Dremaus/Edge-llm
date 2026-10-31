import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';

/// Blokada aplikacji biometrią lub PIN-em telefonu: przy starcie i po powrocie z tła
/// (po [relockAfter]). Treść jest zasłonięta, dopóki użytkownik się nie uwierzytelni.
class AppLock extends StatefulWidget {
  const AppLock({super.key, required this.enabled, required this.child, this.relockAfter = const Duration(minutes: 1)});

  final bool enabled;
  final Widget child;
  final Duration relockAfter;

  @override
  State<AppLock> createState() => _AppLockState();
}

class _AppLockState extends State<AppLock> with WidgetsBindingObserver {
  final _auth = LocalAuthentication();
  bool _locked = true;
  bool _authenticating = false;
  DateTime? _backgroundedAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.enabled) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _unlock());
    } else {
      _locked = false;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!widget.enabled) return;
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _backgroundedAt ??= DateTime.now();
    } else if (state == AppLifecycleState.resumed) {
      final away = _backgroundedAt;
      _backgroundedAt = null;
      if (away != null && DateTime.now().difference(away) >= widget.relockAfter) {
        setState(() => _locked = true);
        _unlock();
      }
    }
  }

  Future<void> _unlock() async {
    if (_authenticating) return;
    _authenticating = true;
    try {
      final ok = await _auth.authenticate(
        localizedReason: 'Odblokuj asystenta / Unlock the assistant',
        options: const AuthenticationOptions(stickyAuth: true),
      );
      if (ok && mounted) setState(() => _locked = false);
    } catch (_) {
      // Brak biometrii/PIN-u na telefonie — zostaje zablokowane z przyciskiem ponowienia.
    } finally {
      _authenticating = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.enabled || !_locked) return widget.child;
    return Scaffold(
      body: Center(
        child: FilledButton.icon(
          onPressed: _unlock,
          icon: const Icon(Icons.lock_open),
          label: const Text('Odblokuj / Unlock'),
        ),
      ),
    );
  }
}
