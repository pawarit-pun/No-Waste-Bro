import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';
import 'task_card.dart';

/// กลุ่มงานตาม action type ในหน้า My tasks: หัวกลุ่มกดพับ / กางได้ + การ์ดงาน
class TaskGroupSection extends StatelessWidget {
  const TaskGroupSection({
    super.key,
    required this.type,
    required this.tasks,
    required this.collapsed,
    required this.onToggle,
    required this.onTapTask,
  });

  final ActionType type;
  final List<Task> tasks;
  final bool collapsed;
  final VoidCallback onToggle;
  final ValueChanged<Task> onTapTask;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _GroupHeader(
          type: type,
          count: tasks.length,
          collapsed: collapsed,
          onTap: onToggle,
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeInOut,
          alignment: Alignment.topCenter,
          child: collapsed
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Column(
                    children: [
                      for (final task in tasks)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: TaskCard(task: task, onTap: () => onTapTask(task)),
                        ),
                    ],
                  ),
                ),
        ),
      ],
    );
  }
}

class _GroupHeader extends StatelessWidget {
  const _GroupHeader({
    required this.type,
    required this.count,
    required this.collapsed,
    required this.onTap,
  });

  final ActionType type;
  final int count;
  final bool collapsed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final style = ActionStyle.of(type);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: style.iconBackground,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(style.icon, size: 18, color: style.tint),
              ),
              const SizedBox(width: 10),
              // ชื่อ + จำนวน กินพื้นที่ที่เหลือทั้งหมด → ลูกศรชิดขวาสุดเท่ากันทุกกลุ่ม
              Expanded(
                child: Row(
                  children: [
                    Flexible(
                      child: Text(
                        actionGroupLabel(type),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                          letterSpacing: -0.2,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: style.badgeBackground,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '$count',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: style.tint,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              AnimatedRotation(
                turns: collapsed ? -0.25 : 0,
                duration: const Duration(milliseconds: 220),
                child: const Icon(Icons.expand_more, color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
