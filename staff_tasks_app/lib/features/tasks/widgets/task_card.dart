import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// การ์ดงาน 1 ใบในหน้า My tasks
class TaskCard extends StatelessWidget {
  const TaskCard({super.key, required this.task, this.onTap});

  final Task task;
  final VoidCallback? onTap;

  bool get _done => task.status == TaskStatus.completed;

  @override
  Widget build(BuildContext context) {
    final base = ActionStyle.of(task.actionType);
    final style = _done ? base.muted() : base;

    return Material(
      color: _done ? AppColors.cardMuted : AppColors.surface,
      borderRadius: BorderRadius.circular(22),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: style.iconBackground,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(style.icon, color: style.tint, size: 24),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Row(
                            children: [
                              Flexible(
                                child: _Badge(label: actionLabel(task), style: style),
                              ),
                              if (!_done) ...[
                                const SizedBox(width: 6),
                                _PriorityBadge(priority: task.priority),
                              ],
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        _TimeText(task: task),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      taskTitle(task),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        height: 1.25,
                        color: _done ? AppColors.textSecondary : AppColors.textPrimary,
                      ),
                    ),
                    if (!_done) ...[
                      const SizedBox(height: 4),
                      Text(
                        taskLotLine(task),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 14, color: AppColors.textSecondary),
                      ),
                    ],
                    const SizedBox(height: 6),
                    _StatusLine(status: task.status),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.style});

  final String label;
  final ActionStyle style;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: style.badgeBackground,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: style.tint),
      ),
    );
  }
}

/// ป้าย priority เช่น "P1" (แสดงเฉพาะงานที่ยังไม่เสร็จ)
class _PriorityBadge extends StatelessWidget {
  const _PriorityBadge({required this.priority});

  final int priority;

  @override
  Widget build(BuildContext context) {
    final (background, foreground) = priorityColors(priority);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(8)),
      child: Text(
        priorityLabel(priority),
        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: foreground),
      ),
    );
  }
}

/// มุมขวาบน: เวลาที่เสร็จ (งานเสร็จแล้ว) หรือ Due / Pickup
/// สีแดงเมื่อเป็นงานด่วนหรือเลยกำหนดแล้ว
class _TimeText extends StatelessWidget {
  const _TimeText({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    if (task.status == TaskStatus.completed) {
      final at = task.completedAt;
      if (at == null) return const SizedBox.shrink();
      return Text(
        hhmm.format(at.toLocal()),
        style: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: AppColors.textSecondary,
        ),
      );
    }

    final due = task.dueBy;
    if (due == null) return const SizedBox.shrink();
    final red = task.priority == 1 || due.isBefore(DateTime.now());
    return Text(
      dueLabel(task, due),
      style: TextStyle(
        fontSize: 15,
        fontWeight: FontWeight.w700,
        color: red ? AppColors.urgent : const Color(0xFF3A3A3C),
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.status});

  final TaskStatus status;

  @override
  Widget build(BuildContext context) {
    return switch (status) {
      TaskStatus.inProgress => Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: const BoxDecoration(
                color: AppColors.statusInProgress,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 6),
            const Text(
              'In progress',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: AppColors.statusInProgress,
              ),
            ),
          ],
        ),
      TaskStatus.completed => const Row(
          children: [
            Icon(Icons.check, size: 15, color: AppColors.statusCompleted),
            SizedBox(width: 4),
            Text(
              'Completed',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: AppColors.statusCompleted,
              ),
            ),
          ],
        ),
      _ => const Row(
          children: [
            Icon(Icons.radio_button_unchecked, size: 13, color: AppColors.statusPending),
            SizedBox(width: 5),
            Text(
              'Pending',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.statusPending,
              ),
            ),
          ],
        ),
    };
  }
}
