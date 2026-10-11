import 'dart:io';

/// 定位「项目根」与「Python 解释器」。
///
/// 纪律：**不硬编码绝对路径**（项目目录可能改名 / 换机）。
/// 依次尝试：环境变量 → 从当前目录向上找标记文件 → 从可执行文件位置向上找。
class ProjectRoot {
  static const _marker = 'python/bridge/serve.py';

  static bool _ok(Directory d) =>
      File('${d.path}${Platform.pathSeparator}python${Platform.pathSeparator}bridge'
          '${Platform.pathSeparator}serve.py').existsSync();

  /// 返回项目根目录（含 python/bridge/serve.py），找不到返回 null。
  static Directory? find() {
    final env = Platform.environment['SUMMONERLENS_ROOT'];
    if (env != null && env.isNotEmpty) {
      final d = Directory(env);
      if (_ok(d)) return d;
    }
    var d = Directory.current;
    for (var i = 0; i < 8; i++) {
      if (_ok(d)) return d;
      final p = d.parent;
      if (p.path == d.path) break;
      d = p;
    }
    var e = File(Platform.resolvedExecutable).parent;
    for (var i = 0; i < 8; i++) {
      if (_ok(e)) return e;
      final p = e.parent;
      if (p.path == e.path) break;
      e = p;
    }
    return null;
  }

  static String get marker => _marker;
}

class PythonLocator {
  /// 返回可用的 Python 可执行文件路径/命令名；找不到返回 null。
  static Future<String?> find() async {
    final env = Platform.environment['SUMMONERLENS_PYTHON'];
    if (env != null && env.isNotEmpty && File(env).existsSync()) return env;
    for (final c in <String>['python', 'python3', 'py']) {
      try {
        final r = await Process.run(c, const ['--version']);
        if (r.exitCode == 0) return c;
      } catch (_) {
        // 继续尝试下一个
      }
    }
    return null;
  }
}
