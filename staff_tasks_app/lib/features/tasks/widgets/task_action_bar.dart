import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// แถบปุ่มด้านล่างของหน้า Task detail
class TaskActionBar extends StatelessWidget {
  const TaskActionBar({
    super.key,
    required this.task,
    required this.busy,
    required this.onReject,
    required this.onStart,
    required this.onComplete,
  });

  final Task task;
  final bool busy;
  final VoidCallback onReject;
  final VoidCallback onStart;
  final VoidCallback onComplete;

  @override
  Widget build(BuildContext context) {
    final Widget content = switch (task.status) {
      TaskStatus.pending || TaskStatus.inProgress => Row(
          children: [
            Expanded(
              flex: 2,
              child: SizedBox(
                height: 56,
                child: OutlinedButton.icon(
                  onPressed: busy ? null : onReject,
                  icon: const Icon(Icons.close, size: 20),
                  label: const Text('Reject'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.urgent,
                    side: const BorderSide(color: AppColors.chipBorder),
                    shape: const StadiumBorder(),
                    textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 3,
              child: SizedBox(
                height: 56,
                child: FilledButton.icon(
                  onPressed: busy
                      ? null
                      : (task.status == TaskStatus.pending ? onStart : onComplete),
                  icon: busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : Icon(
                          task.status == TaskStatus.pending ? Icons.play_arrow : Icons.check,
                          size: 20,
                        ),
                  label: Text(task.status == TaskStatus.pending ? 'Start task' : 'Complete task'),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.textPrimary,
                    disabledBackgroundColor: AppColors.textSecondary,
                    foregroundColor: Colors.white,
                    disabledForegroundColor: Colors.white,
                    shape: const StadiumBorder(),
                    textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ),
          ],
        ),
      TaskStatus.completed => _Note(
          icon: Icons.check_circle,
          color: AppColors.statusCompleted,
          text: [
            'Completed',
            if (task.completedAt != null) hhmm.format(task.completedAt!.toLocal()),
            if (task.actualQuantityHandled != null)
              '${quantityLabel(task.actualQuantityHandled!, task.product?.unitOfMeasure ?? 'PIECE')} handled',
          ].join(' · '),
        ),
      TaskStatus.rejected => _Note(
          icon: Icons.cancel,
          color: AppColors.urgent,
          text: 'Rejected · ${task.rejectionReason ?? '-'}',
        ),
    };

    return Container(
      decoration: const BoxDecoration(
        color: Color(0xFFF7F7F8),
        border: Border(top: BorderSide(color: AppColors.divider)),
      ),
      padding: EdgeInsets.fromLTRB(20, 14, 20, MediaQuery.paddingOf(context).bottom + 14),
      child: content,
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({required this.icon, required this.color, required this.text});

  final IconData icon;
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: color),
            ),
          ),
        ],
      ),
    );
  }
}
