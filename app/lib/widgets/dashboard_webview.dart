import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';

import '../theme.dart';

/// webview（WebView2）封装：装载本地 ECharts 仪表板，带加载中 / 错误态。
///
/// **时序契约（重要）**：`WebviewController.initialize()` 必须在 **任何** 其它调用
/// （`loadUrl` / `reload` / `executeScript` …）之前完成 —— 插件的 `_methodChannel`
/// 是 `late` 字段，只在 `initialize()` 里赋值；未初始化就调用会抛
/// `LateInitializationError: Field '_methodChannel' has not been initialized`。
///
/// 因此本组件在 `initialize()` 成功后才回调 [onInitialized]，
/// **父级必须等到该回调触发后**才可以操作 controller。
class DashboardWebview extends StatefulWidget {
  const DashboardWebview({
    super.key,
    required this.controller,
    this.onInitialized,
    this.onReady,
    this.onLoadError,
  });

  final WebviewController controller;

  /// controller 初始化完成（**此时才可以安全调用 loadUrl 等**）。
  final VoidCallback? onInitialized;

  /// 页面导航完成（首屏可见）。
  final VoidCallback? onReady;

  /// 导航级错误（不替换视图，由父级提示，便于用户点「刷新」重试）。
  final ValueChanged<String>? onLoadError;

  @override
  State<DashboardWebview> createState() => _DashboardWebviewState();
}

class _DashboardWebviewState extends State<DashboardWebview> {
  final List<StreamSubscription<dynamic>> _subs = <StreamSubscription<dynamic>>[];
  bool _inited = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_init());
  }

  Future<void> _init() async {
    final c = widget.controller;
    try {
      if (!_inited) {
        await c.initialize();
        _inited = true;
      }
      if (!mounted) return;
      // 先开始监听再通知外部装载，避免错过首次 loading 事件
      _subs.add(c.loadingState.listen((LoadingState state) {
        if (!mounted) return;
        setState(() => _loading = state == LoadingState.loading);
        if (state == LoadingState.navigationCompleted) {
          widget.onReady?.call();
        }
      }));
      _subs.add(c.onLoadError.listen((WebErrorStatus err) {
        if (!mounted) return;
        setState(() => _loading = false);
        widget.onLoadError?.call('$err');
      }));
      widget.onInitialized?.call();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  void dispose() {
    for (final StreamSubscription<dynamic> s in _subs) {
      unawaited(s.cancel());
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
