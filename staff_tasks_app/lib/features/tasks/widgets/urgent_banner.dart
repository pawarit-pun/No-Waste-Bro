import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// แถบ "N Urgent tasks due before HH:mm"
/// HH:mm = เวลา due ที่ช้าที่สุดของงานด่วน (ถ้าไม่มีงานไหนมี due จะไม่แสดงเวลา)
class UrgentBanner extends StatelessWidget {
  const UrgentBanner({super.key, required this.tasks, this.onTap});

  final List<Task> tasks;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final dues = tasks.map((t) => t.dueBy).whereType<DateTime>().toList();
    final latest = dues.isEmpty ? null : dues.reduce((a, b) => a.isAfter(b) ? a : b);
    final noun = tasks.length == 1 ? 'Urgent task' : 'Urgent tasks';
    final text = latest == null ? noun : '$noun due before ${hhmm.format(latest.toLocal())}';

    return Material(
      color: Colors.white.withValues(alpha: 0.8),
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          child: Row(
            children: [
              Container(
                width: 32,
                height: 32,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.urgentBadge,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${tasks.length}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  text,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                ),
              ),
              const Icon(Icons.chevron_right, color: AppColors.textPrimary),
            ],
          ),
        ),
      ),
    );
  }
}
