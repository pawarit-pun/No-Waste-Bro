import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// การ์ดใหญ่ด้านบนของหน้า Task detail
class DetailHero extends StatelessWidget {
  const DetailHero({super.key, required this.task});

  final Task task;

  String get _unit => task.product?.unitOfMeasure ?? 'PIECE';

  /// ตัวเลขใหญ่ + คำอธิบายเล็กใต้ตัวเลข
  (String, String?) get _headline => switch (task.actionType) {
        ActionType.markdown => ('-${percentLabel(task.discountPct)}', null),
        ActionType.kitchenRepurpose => ('×${task.batchCount ?? 1}', 'batches'),
        ActionType.donate => (
            '${task.actionQuantity}',
            '${quantityLabel(task.actionQuantity, _unit).split(' ').last} to donate'
          ),
        ActionType.discard => (
            '${task.actionQuantity}',
            '${quantityLabel(task.actionQuantity, _unit).split(' ').last} to discard'
          ),
      };

  @override
  Widget build(BuildContext context) {
    final style = ActionStyle.of(task.actionType);
    final (big, caption) = _headline;
    final riskLevel = task.assessment?['risk_level'] as String?;

    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(28),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ส่วนไล่สีด้านบน
          Container(
            height: 168,
            padding: const EdgeInsets.fromLTRB(22, 20, 22, 20),
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(0.6, -1.0),
                radius: 1.3,
                colors: [style.badgeBackground, style.iconBackground, Colors.white],
                stops: const [0.0, 0.55, 1.0],
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(
                          big,
                          style: TextStyle(
                            fontSize: 64,
                            fontWeight: FontWeight.w800,
                            letterSpacing: -2,
                            height: 1,
                            color: style.tint,
                          ),
                        ),
                      ),
                      if (caption != null)
                        Text(
                          caption,
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: style.tint,
                          ),
                        ),
                    ],
                  ),
                ),
                Icon(style.icon, size: 56, color: style.tint),
              ],
            ),
          ),
          // ข้อมูลงาน
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    _Pill(
                      label: task.actionType == ActionType.markdown
                          ? 'Markdown'
                          : actionLabel(task),
                      background: style.badgeBackground,
                      foreground: style.tint,
                    ),
                    if (riskLevel != null)
                      _Pill(
                        label: riskLabel(riskLevel),
                        background: riskColors(riskLevel).$1,
                        foreground: riskColors(riskLevel).$2,
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  taskTitle(task),
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.4,
                    height: 1.2,
                  ),
                ),
                const SizedBox(height: 12),
                ..._infoRows(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _infoRows() {
    final lot = task.lot;
    final product = task.product;
    final rows = <Widget>[];

    if (lot != null) {
      rows.add(_InfoRow(
        icon: Icons.inventory_2_outlined,
        text: 'Lot ${lot.lotId} · ${quantityLabel(lot.currentQuantity, _unit)} in stock',
      ));
      final place = [lot.locationAisle, lot.locationShelf].whereType<String>().join(' · ');
      final category = product == null ? null : categoryLabels[product.category];
      if (place.isNotEmpty) {
        rows.add(_InfoRow(
          icon: Icons.place_outlined,
          text: category == null ? place : '$place ($category)',
        ));
      }
    }

    final parts = [
      if (task.dueBy != null) dueDayLabel(task.dueBy!),
      if (lot != null) expiresLabel(lot.expirationDate),
    ];
    if (parts.isNotEmpty) {
      final active =
          task.status == TaskStatus.pending || task.status == TaskStatus.inProgress;
      rows.add(_InfoRow(
        icon: Icons.schedule,
        text: parts.join(' · '),
        color: active ? AppColors.urgent : AppColors.textSecondary,
        bold: active,
      ));
    }
    return rows;
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.background, required this.foreground});

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(8)),
      child: Text(
        label,
        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: foreground),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.icon,
    required this.text,
    this.color = AppColors.textPrimary,
    this.bold = false,
  });

  final IconData icon;
  final String text;
  final Color color;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: bold ? color : AppColors.textSecondary),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 15,
                color: color,
                fontWeight: bold ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
