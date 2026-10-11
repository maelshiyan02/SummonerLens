import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_windows/webview_windows.dart';

import '../services/bridge_service.dart';
import '../theme.dart';
import '../widgets/dashboard_webview.dart';

/// 桌面主壳：左侧导航（概览 / 排名 / 协同 / 分层）+ 顶栏筛选 + 中央 webview。
///
/// 数据流：本壳拉起 Python bridge（本地 HTTP）→ webview 装载仪表板；
/// 导航与筛选通过改写 URL 查询参数驱动同一个仪表板（筛选器联动数据层）。
///
/// **时序契约（重要）**：`WebviewController.initialize()` 必须先于 `loadUrl()` 完成，
/// 否则插件抛 `LateInitializationError: Field '_methodChannel' has not been initialized`。
/// 为此：
///   1) webview 由本页**常驻挂载**（不再等 baseUrl 就绪），使其初始化与起服务并行；
///   2) `_navigate()` 受 [_webviewReady] 门控；
///   3) 两条异步链路（起服务 / 初始化 webview）**谁后完成谁触发一次导航**，
///      保证「服务就绪」与「controller 就绪」两个条件同时满足时才装载。
class ShellPage extends StatefulWidget {
  const ShellPage({super.key});

  @override
  State<ShellPage> createState() => _ShellPageState();
}

class _ShellPageState extends State<ShellPage> {
  final BridgeService _bridge = BridgeService();
  final WebviewController _wc = WebviewController();

  int _navIndex = 0;
  String _dataset = 'real'; // real | fixture
  String? _baseUrl;
  String? _fatal;
  String _stage = '正在启动本地服务…';
  bool _webviewReady = false; // controller 已 initialize（可安全 loadUrl）
  bool _pageReady = false; // 页面导航完成

  static const _tabs = <String>['overview', 'ranking', 'synergy', 'strata'];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _boot());
  }

  // ------------------------------------------------------------------ 启动

  Future<void> _boot() async {
    try {
      if (mounted) setState(() => _stage = '定位 Python 与项目根…');
      final url = await _bridge.start();
      if (!mounted) return;
      setState(() {
        _baseUrl = url;
        _stage = '服务就绪：$url';
      });
      await _navigate(); // webview 若尚未就绪，会在 _onWebviewInitialized 里补上
    } catch (e) {
      if (!mounted) return;
      setState(() => _fatal = '$e');
    }
  }

  void _onWebviewInitialized() {
    if (!mounted) return;
    setState(() => _webviewReady = true);
    unawaited(_navigate()); // 服务若已就绪，立即装载
  }

  void _onPageReady() {
    if (!mounted) return;
    setState(() {
      _pageReady = true;
      _stage = '已装载 ${_baseUrl ?? ''}';
    });
  }

  // ------------------------------------------------------------------ 导航

  String _url({bool bust = false}) {
    final q = 'tab=${_tabs[_navIndex]}&dataset=$_dataset';
    return bust ? '$_baseUrl?$q&t=${DateTime.now().millisecondsSinceEpoch}' : '$_baseUrl?$q';
  }

  /// 装载当前 URL。**必须等到 controller 初始化完成**（否则插件会抛错）。
  Future<void> _navigate({bool bust = false}) async {
    if (_baseUrl == null || !_webviewReady) return;
    try {
      if (mounted) setState(() => _stage = '正在装载…');
      await _wc.loadUrl(_url(bust: bust));
    } catch (e) {
      if (mounted) setState(() => _stage = '装载失败：$e');
    }
  }

  Future<void> _rebuild() async {
    setState(() => _stage = '正在重建数据束…');
    final bool ok = await _bridge.rebuildBundle();
    await _navigate(bust: true); // 带时间戳，绕过任何缓存
    if (!mounted) return;
    setState(() => _stage = ok ? '数据束已重建' : '重建失败（详见日志）');
  }

  Future<void> _openInBrowser() async {
    if (_baseUrl == null) return;
    await launchUrl(Uri.parse(_url()), mode: LaunchMode.externalApplication);
  }

  void _showLogs() {
    showDialog<void>(
      context: context,
      builder: (BuildContext ctx) => AlertDialog(
        backgroundColor: SLTheme.panel,
        title: const Text('bridge 日志'),
        content: SizedBox(
          width: 640,
          height: 360,
          child: SingleChildScrollView(
            child: SelectableText(
              _bridge.logs.join('\n'),
              style: const TextStyle(fontFamily: 'Consolas', fontSize: 12),
            ),
          ),
        ),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('关闭')),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _bridge.stop();
    // 仅当 controller 已 initialize 时才释放：未初始化时插件的 late 字段会抛错
    if (_webviewReady) unawaited(_wc.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: <Widget>[
          _topBar(),
          const Divider(height: 1),
          Expanded(child: _body()),
          const Divider(height: 1),
          _statusBar(),
        ],
      ),
    );
  }

  Widget _topBar() {
    return Container(
      color: SLTheme.bg2,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        children: <Widget>[
          Container(
            width: 10,
            height: 22,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(3),
              gradient: const LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: <Color>[SLTheme.tierHigh, Color(0xFF7B6BFF)],
              ),
            ),
          ),
          const SizedBox(width: 10),
          const Text('SummonerLens',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
          const SizedBox(width: 10),
          const Text('召唤师数据分析助手 · 海克斯大乱斗',
              style: TextStyle(color: SLTheme.muted, fontSize: 12)),
          const Spacer(),
          SegmentedButton<String>(
            segments: const <ButtonSegment<String>>[
              ButtonSegment<String>(value: 'real', label: Text('真实聚合')),
              ButtonSegment<String>(value: 'fixture', label: Text('合成夹具')),
            ],
            selected: <String>{_dataset},
            onSelectionChanged: (Set<String> s) {
              setState(() => _dataset = s.first);
              unawaited(_navigate());
            },
            showSelectedIcon: false,
            style: const ButtonStyle(visualDensity: VisualDensity.compact),
          ),
          const SizedBox(width: 12),
          IconButton(
            tooltip: '刷新',
            onPressed: () => unawaited(_navigate()),
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: '重建数据束（联动数据层）',
            onPressed: () => unawaited(_rebuild()),
            icon: const Icon(Icons.build_outlined),
          ),
          IconButton(
            tooltip: '在系统浏览器打开',
            onPressed: () => unawaited(_openInBrowser()),
            icon: const Icon(Icons.open_in_new),
          ),
          IconButton(
            tooltip: 'bridge 日志',
            onPressed: _showLogs,
            icon: const Icon(Icons.article_outlined),
          ),
        ],
      ),
    );
  }

  Widget _body() {
    if (_fatal != null) return _fatalPane(_fatal!);
    // webview 常驻挂载（与起服务并行），服务未就绪时用遮罩盖住
    return Row(
      children: <Widget>[
        NavigationRail(
          selectedIndex: _navIndex,
          onDestinationSelected: (int i) {
            setState(() => _navIndex = i);
            unawaited(_navigate());
          },
          labelType: NavigationRailLabelType.all,
          destinations: const <NavigationRailDestination>[
            NavigationRailDestination(
                icon: Icon(Icons.dashboard_outlined),
                selectedIcon: Icon(Icons.dashboard),
                label: Text('概览')),
            NavigationRailDestination(
                icon: Icon(Icons.leaderboard_outlined),
                selectedIcon: Icon(Icons.leaderboard),
                label: Text('排名')),
            NavigationRailDestination(
                icon: Icon(Icons.hub_outlined),
                selectedIcon: Icon(Icons.hub),
                label: Text('协同')),
            NavigationRailDestination(
                icon: Icon(Icons.layers_outlined),
                selectedIcon: Icon(Icons.layers),
                label: Text('分层')),
          ],
        ),
        const VerticalDivider(width: 1),
        Expanded(
          child: Stack(
            children: <Widget>[
              DashboardWebview(
                controller: _wc,
                onInitialized: _onWebviewInitialized,
                onReady: _onPageReady,
                onLoadError: (String e) {
                  if (mounted) setState(() => _stage = '装载失败：$e');
                },
              ),
              if (_baseUrl == null) Positioned.fill(child: _bootingPane()),
            ],
          ),
        ),
      ],
    );
  }

  Widget _bootingPane() {
    return Container(
      color: SLTheme.bg,
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            const CircularProgressIndicator(color: SLTheme.accent),
            const SizedBox(height: 16),
            Text(_stage, style: const TextStyle(color: SLTheme.muted)),
            const SizedBox(height: 4),
            const Text('首次启动需构建数据束，可能耗时数十秒',
                style: TextStyle(color: SLTheme.muted, fontSize: 12)),
          ],
        ),
      ),
    );
  }

  Widget _fatalPane(String msg) {
    final String root = Directory.current.path;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            const Icon(Icons.link_off, size: 46, color: SLTheme.up),
            const SizedBox(height: 14),
            const Text('无法启动本地数据服务', style: TextStyle(fontSize: 16)),
            const SizedBox(height: 10),
            SelectableText(msg,
                style: const TextStyle(color: SLTheme.muted, fontSize: 12)),
            const SizedBox(height: 18),
            const Text('排查建议：', style: TextStyle(color: SLTheme.text)),
            const SizedBox(height: 6),
            SelectableText(
              '1) 安装 Python 3 并加入 PATH，或设置环境变量 SUMMONERLENS_PYTHON\n'
              '2) 设置 SUMMONERLENS_ROOT 指向项目根（含 python/bridge/serve.py）\n'
              '3) 手动验证：python python/bridge/serve.py --open\n'
              '当前工作目录：$root',
              style: const TextStyle(color: SLTheme.muted, fontSize: 12),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: () {
                setState(() {
                  _fatal = null;
                  _stage = '重试中…';
                });
                unawaited(_boot());
              },
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusBar() {
    final IconData icon = _pageReady
        ? Icons.cloud_done
        : (_baseUrl == null ? Icons.hourglass_empty : Icons.cloud_queue);
    return Container(
      color: SLTheme.bg2,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      child: Row(
        children: <Widget>[
          Icon(icon, size: 14, color: _pageReady ? SLTheme.down : SLTheme.muted),
          const SizedBox(width: 6),
          Expanded(
            child: Text(_stage,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: SLTheme.muted, fontSize: 12)),
          ),
          Text('数据源：${_dataset == 'real' ? 'hexdata 真实聚合' : '合成夹具（仅引擎校验）'}',
              style: const TextStyle(color: SLTheme.muted, fontSize: 12)),
        ],
      ),
    );
  }
}
