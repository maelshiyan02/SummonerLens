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
  bool _ready = false;

  static const _tabs = <String>['overview', 'ranking', 'synergy', 'strata'];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _boot());
  }

  Future<void> _boot() async {
    try {
      setState(() {
        _stage = '定位 Python 与项目根…';
      });
      final url = await _bridge.start();
      if (!mounted) return;
      setState(() {
        _baseUrl = url;
        _stage = '服务就绪：$url';
      });
      await _navigate();
    } catch (e) {
      if (!mounted) return;
      setState(() => _fatal = '$e');
    }
  }

  String _url() => '$_baseUrl?tab=${_tabs[_navIndex]}&dataset=$_dataset';

  Future<void> _navigate() async {
    if (_baseUrl == null) return;
    try {
      await _wc.loadUrl(_url());
    } catch (e) {
      if (mounted) setState(() => _stage = '装载失败：$e');
    }
  }

  Future<void> _rebuild() async {
    setState(() => _stage = '正在重建数据束…');
    final ok = await _bridge.rebuildBundle();
    await _navigate();
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
      builder: (ctx) => AlertDialog(
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
    _wc.dispose();
    _bridge.stop();
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
              _navigate();
            },
            showSelectedIcon: false,
            style: const ButtonStyle(visualDensity: VisualDensity.compact),
          ),
          const SizedBox(width: 12),
          IconButton(
            tooltip: '刷新',
            onPressed: _navigate,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: '重建数据束（联动数据层）',
            onPressed: _rebuild,
            icon: const Icon(Icons.build_outlined),
          ),
          IconButton(
            tooltip: '在系统浏览器打开',
            onPressed: _openInBrowser,
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
    if (_fatal != null) {
      return _fatalPane(_fatal!);
    }
    if (_baseUrl == null) {
      return Center(
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
      );
    }
    return Row(
      children: <Widget>[
        NavigationRail(
          selectedIndex: _navIndex,
          onDestinationSelected: (int i) {
            setState(() => _navIndex = i);
            _navigate();
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
          child: DashboardWebview(
            controller: _wc,
            onReady: () {
              if (mounted && !_ready) setState(() => _ready = true);
            },
          ),
        ),
      ],
    );
  }

  Widget _fatalPane(String msg) {
    final root = Directory.current.path;
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
                _boot();
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
    return Container(
      color: SLTheme.bg2,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      child: Row(
        children: <Widget>[
          Icon(
            _baseUrl == null ? Icons.hourglass_empty : Icons.check_circle,
            size: 14,
            color: _baseUrl == null ? SLTheme.muted : SLTheme.down,
          ),
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
