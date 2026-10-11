import 'package:flutter/material.dart';

/// 深色默认主题（与 web 仪表板同一套配色，两站共识：深色默认）。
class SLTheme {
  static const bg = Color(0xFF0B0F16);
  static const bg2 = Color(0xFF0F141D);
  static const panel = Color(0xFF141A24);
  static const panel2 = Color(0xFF1A2230);
  static const border = Color(0x22FFFFFF);
  static const text = Color(0xFFE6EDF7);
  static const muted = Color(0xFF8A93A6);
  static const accent = Color(0xFF4A9EFF);
  static const up = Color(0xFFFF5B5B); // 涨/高 → 红（中文习惯）
  static const down = Color(0xFF3FC76A); // 跌/低 → 绿
  static const tierHigh = Color(0xFFE8B23A);

  static ThemeData dark() {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: bg,
      colorScheme: base.colorScheme.copyWith(
        brightness: Brightness.dark,
        primary: accent,
        secondary: tierHigh,
        surface: panel,
        onSurface: text,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: bg2,
        foregroundColor: text,
        elevation: 0,
        centerTitle: false,
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: bg2,
        indicatorColor: accent.withValues(alpha: 0.18),
        selectedIconTheme: const IconThemeData(color: accent),
        unselectedIconTheme: const IconThemeData(color: muted),
        selectedLabelTextStyle: const TextStyle(color: accent, fontSize: 12),
        unselectedLabelTextStyle: const TextStyle(color: muted, fontSize: 12),
      ),
      dividerTheme: const DividerThemeData(color: border, space: 1, thickness: 1),
      textTheme: base.textTheme.apply(bodyColor: text, displayColor: text),
    );
  }
}
