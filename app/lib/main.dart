import 'package:flutter/material.dart';

import 'pages/shell_page.dart';
import 'theme.dart';

/// SummonerLens 桌面入口。
///
/// 形态：Flutter Desktop 壳（本地优先、零后端、可离线）。
/// 可视化：内嵌 WebView2 装载本地 ECharts 仪表板（app/web）。
/// 数据层：由壳拉起 Python bridge（python/bridge/serve.py）提供本地 HTTP。
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SummonerLensApp());
}

class SummonerLensApp extends StatelessWidget {
  const SummonerLensApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SummonerLens · 召唤师数据分析助手',
      debugShowCheckedModeBanner: false,
      theme: SLTheme.dark(),
      home: const ShellPage(),
    );
  }
}
