import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';

import '../theme.dart';

/// webview（WebView2）封装：装载本地 ECharts 仪表板，带加载中 / 错误态。
///
/// 只使用 webview_windows 的稳定 API：initialize / loadUrl / loadingState。
class DashboardWebview extends StatefulWidget {
  const DashboardWebview({super.key, required this.controller, this.onReady});

  final WebviewController controller;
  final VoidCallback? onReady;

  @override
  State<DashboardWebview> createState() => _DashboardWebviewState();
}

class _DashboardWebviewState extends State<DashboardWebview> {
  final List<StreamSubscription<LoadingState>> _subs =
      <StreamSubscription<LoadingState>>[];
  bool _inited = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final c = widget.controller;
    try {
      if (!_inited) {
        await c.initialize();
        _inited = true;
      }
      _subs.add(c.loadingState.listen((state) {
        if (!mounted) return;
        setState(() => _loading = state == LoadingState.loading);
        if (state == LoadingState.navigationCompleted) {
          widget.onReady?.call();
        }
      }));
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return _ErrorPane(message: _error!);
    }
    return Stack(
      children: <Widget>[
        Webview(widget.controller),
        if (_loading)
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: LinearProgressIndicator(minHeight: 2, color: SLTheme.accent),
          ),
      ],
    );
  }
}

class _ErrorPane extends StatelessWidget {
  const _ErrorPane({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            const Icon(Icons.error_outline, size: 44, color: SLTheme.up),
            const SizedBox(height: 12),
            const Text('WebView 载入失败', style: TextStyle(fontSize: 16)),
            const SizedBox(height: 8),
            SelectableText(message,
                style: const TextStyle(color: SLTheme.muted, fontSize: 12)),
            const SizedBox(height: 12),
            const Text('提示：Windows 内嵌 WebView 需要 WebView2 运行时（Win11 自带）。',
                style: TextStyle(color: SLTheme.muted, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
