import 'package:flutter/material.dart';

import '../models/task.dart';

/// สีและ theme ตามดีไซน์ (ฟอนต์ใช้ฟอนต์ระบบของ iOS)
class AppColors {
  AppColors._();

  static const orange = Color(0xFFE8622C);
  static const orangeSoft = Color(0xFFF4A97F);
  static const background = Color(0xFFEDEDEF);
  static const surface = Colors.white;
  static const textPrimary = Color(0xFF1C1C1E);
  static const textSecondary = Color(0xFF6E6E73);
  static const divider = Color(0xFFE5E5EA);

  // หน้า My tasks
  static const urgent = Color(0xFFC0281C); // เวลา due ของงานด่วน / เลยกำหนด
  static const urgentBadge = Color(0xFFC2410C); // กล่องตัวเลขในแบนเนอร์ Urgent

  // สีสถานะ task
  static const statusPending = Color(0xFF007AFF);
  static const statusInProgress = orange;
  static const statusCompleted = Color(0xFF248A3D);
  static const inProgress = statusInProgress;
  static const cardMuted = Color(0xFFF5F5F7); // การ์ดงานที่เสร็จแล้ว
  static const chipBorder = Color(0xFFD1D1D6);
}

/// ไอคอนและสีของแต่ละประเภทงาน
class ActionStyle {
  const ActionStyle({
    required this.icon,
    required this.tint,
    required this.iconBackground,
    required this.badgeBackground,
  });

  final IconData icon;

  /// สีไอคอนและตัวหนังสือในป้าย
  final Color tint;
  final Color iconBackground;
  final Color badgeBackground;

  static ActionStyle of(ActionType type) => switch (type) {
        ActionType.markdown => const ActionStyle(
            icon: Icons.sell_outlined,
            tint: Color(0xFFC2410C),
            iconBackground: Color(0xFFFCD9C5),
            badgeBackground: Color(0xFFFAD0B9),
          ),
        ActionType.kitchenRepurpose => const ActionStyle(
            icon: Icons.soup_kitchen_outlined,
            tint: Color(0xFF8A6100),
            iconBackground: Color(0xFFF7E6B5),
            badgeBackground: Color(0xFFF5E0A3),
          ),
        ActionType.donate => const ActionStyle(
            icon: Icons.local_shipping_outlined,
            tint: Color(0xFF2E7D32),
            iconBackground: Color(0xFFDCEFDC),
            badgeBackground: Color(0xFFCDE8CF),
          ),
        ActionType.discard => const ActionStyle(
            icon: Icons.delete_outline,
            tint: Color(0xFF48484A),
            iconBackground: Color(0xFFE5E5EA),
            badgeBackground: Color(0xFFE3E3E8),
          ),
      };

  /// สีเทาสำหรับงานที่เสร็จแล้ว (ไอคอนเดิม)
  ActionStyle muted() => ActionStyle(
        icon: icon,
        tint: AppColors.textSecondary,
        iconBackground: const Color(0xFFE5E5EA),
        badgeBackground: const Color(0xFFE5E5EA),
      );
}

class AppTheme {
  AppTheme._();

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.orange,
      primary: AppColors.orange,
      surface: AppColors.surface,
    );
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.background,
      dividerColor: AppColors.divider,
      progressIndicatorTheme: const ProgressIndicatorThemeData(color: AppColors.orange),
    );
    return base.copyWith(
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
    );
  }
}

/// สีป้ายสถานะ task
Color statusColor(TaskStatus status) => switch (status) {
      TaskStatus.pending => AppColors.statusPending,
      TaskStatus.inProgress => AppColors.statusInProgress,
      TaskStatus.completed => AppColors.statusCompleted,
      TaskStatus.rejected => AppColors.urgent,
    };

/// สีป้ายระดับความเสี่ยง (พื้น, ตัวหนังสือ)
(Color, Color) riskColors(String level) => switch (level) {
      'CRITICAL' => (AppColors.urgent, Colors.white),
      'HIGH' => (const Color(0xFFFBD5D5), AppColors.urgent),
      'MEDIUM' => (const Color(0xFFFFF0C2), const Color(0xFF8A6100)),
      _ => (const Color(0xFFDDF3E4), AppColors.statusCompleted),
    };
