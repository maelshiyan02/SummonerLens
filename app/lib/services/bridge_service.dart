import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'python_locator.dart';

/// 本地可视化服务（bridge）生命周期管理。
///
/// 由 Flutter 壳拉起 `python python/bridge/serve.py --port=0`，
/// 解析其 stdout 的 `SUMMONERLENS_SERVE http://127.0.0.1:<port>/` 得到 webview 的装载地址。
/// 首次启动若数据束缺失，serve.py 会先构建（约数十秒），因此超时给足 120s。
class BridgeService {
  Process? _proc;
  String? _baseUrl;
  final List<String> logs = <String>[];
  static const marker = 'SUMMONERLENS_SERVE';

  String? get baseUrl => _baseUrl;
  bool get isRunning => _proc != null && _baseUrl != null;

  Future<String> start({bool rebuild = false}) async {
    if (_baseUrl != null && _proc != null) return _baseUrl!;

    final root = ProjectRoot.find();
    if (root == null) {
      throw StateError('未找到项目根（需包含 ${ProjectRoot.marker}）。'
          '可设置环境变量 SUMMONERLENS_ROOT 指向项目根目录。');
    }
    final py = await PythonLocator.find();
    if (py == null) {
      throw StateError('未找到 Python 解释器。请安装 Python 3 或设置 SUMMONERLENS_PYTHON。');
    }

    final script = '${root.path}${Platform.pathSeparator}python'
        '${Platform.pathSeparator}bridge${Platform.pathSeparator}serve.py';
    if (!File(script).existsSync()) {
      throw StateError('缺少本地服务脚本：$script');
    }

    _log('[bridge] python = $py');
    _log('[bridge] script = $script');
    _proc = await Process.start(py, <String>[script, '--port=0'],
        workingDirectory: root.path);

    final completer = Completer<String>();
    _proc!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      _log(line);
      if (line.startsWith(marker)) {
        final url = line.substring(marker.length).trim();
        _baseUrl = url;
        if (!completer.isCompleted) completer.complete(url);
      }
    });
    _proc!.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) => _log('[serve] $line'));

    unawaited(_proc!.exitCode.then((code) {
      _log('[bridge] 进程退出码=$code');
      _baseUrl = null;
      if (!completer.isCompleted) {
        completer.completeError(StateError('本地服务提前退出（码 $code），详见日志。'));
      }
    }));

    final url = await completer.future.timeout(
      const Duration(seconds: 120),
      onTimeout: () => throw StateError('本地服务启动超时（首次可能需构建数据束，请稍后重试）。'),
    );
    if (rebuild) await rebuildBundle();
    return url;
  }

  /// 联动数据层：请求服务端重建数据束（调 build_viz_bundle）。
  Future<bool> rebuildBundle() async {
    if (_baseUrl == null) return false;
    final uri = Uri.parse('${_baseUrl}api/rebuild');
    try {
      final client = HttpClient();
      final req = await client.postUrl(uri);
      final resp = await req.close();
      final body = await resp.transform(utf8.decoder).join();
      client.close();
      _log('[bridge] rebuild -> ${resp.statusCode} $body');
      return resp.statusCode == 200 && body.contains('"ok":true');
    } catch (e) {
      _log('[bridge] rebuild 失败：$e');
      return false;
    }
  }

  Future<Map<String, dynamic>?> health() async {
    if (_baseUrl == null) return null;
    try {
      final client = HttpClient();
      final req = await client.getUrl(Uri.parse('${_baseUrl}api/health'));
      final resp = await req.close();
      final body = await resp.transform(utf8.decoder).join();
      client.close();
      return jsonDecode(body) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  void _log(String s) {
    logs.add(s);
    if (logs.length > 400) logs.removeAt(0);
  }

  Future<void> stop() async {
    final p = _proc;
    _proc = null;
    _baseUrl = null;
    if (p != null) {
      p.kill();
      try {
        await p.exitCode.timeout(const Duration(seconds: 5));
      } catch (_) {
        p.kill(ProcessSignal.sigkill);
      }
    }
  }
}
