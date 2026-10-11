import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:summonerlens/services/bridge_service.dart';
import 'package:summonerlens/services/python_locator.dart';
import 'package:summonerlens/theme.dart';

/// 无 GUI 的纯逻辑单测（可在 headless 下跑：`flutter test`）。
void main() {
  group('主题', () {
    test('深色默认主题关键色已定义', () {
      expect(SLTheme.bg, const Color(0xFF0B0F16));
      expect(SLTheme.up, const Color(0xFFFF5B5B)); // 涨/高 → 红
      expect(SLTheme.down, const Color(0xFF3FC76A)); // 跌/低 → 绿
      final t = SLTheme.dark();
      expect(t.brightness, Brightness.dark);
      expect(t.scaffoldBackgroundColor, SLTheme.bg);
    });
  });

  group('项目根定位', () {
    test('能从 app/ 向上找到含 python/bridge/serve.py 的项目根', () {
      final root = ProjectRoot.find();
      expect(root, isNotNull, reason: '应能定位项目根（${ProjectRoot.marker}）');
      final script = File(
          '${root!.path}${Platform.pathSeparator}python${Platform.pathSeparator}bridge${Platform.pathSeparator}serve.py');
      expect(script.existsSync(), isTrue);
      final web = Directory(
          '${root.path}${Platform.pathSeparator}app${Platform.pathSeparator}web');
      expect(web.existsSync(), isTrue, reason: 'app/web 应为仪表板目录');
      final dashboard = File(
          '${web.path}${Platform.pathSeparator}data${Platform.pathSeparator}dashboard.json');
      // dashboard.json 是**派生**产物（.gitignore 排除），未构建时跳过而非判失败
      if (dashboard.existsSync()) {
        expect(dashboard.lengthSync(), greaterThan(1000));
      } else {
        markTestSkipped('数据束未生成，先运行 python python/bridge/build_viz_bundle.py');
      }
    });
  });

  group('bridge 服务', () {
    test('marker 协议常量与 serve.py 约定一致', () {
      expect(BridgeService.marker, 'SUMMONERLENS_SERVE');
    });
    test('未启动时 baseUrl 为空且健康检查返回 null', () async {
      final b = BridgeService();
      expect(b.baseUrl, isNull);
      expect(await b.health(), isNull);
      expect(b.isRunning, isFalse);
    });
  });
}
