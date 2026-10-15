import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import '../task_providers.dart';

/// แท็บกรอง All N / Pending / In progress / Done
class TaskFilterChips extends StatelessWidget {
  const TaskFilterChips({
    super.key,
    required this.total,
    required this.selected,
    required this.onSelected,
  });

  final int total;
  final TaskFilter selected;
  final ValueChanged<TaskFilter> onSelected;

  String _label(TaskFilter f) => switch (f) {
        TaskFilter.all => 'All $total',
        TaskFilter.pending => 'Pending',
        TaskFilter.inProgress => 'In progress',
        TaskFilter.done => 'Done',
      };

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      clipBehavior: Clip.none,
      child: Row(
        children: [
          for (final f in TaskFilter.values)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: _Chip(
                label: _label(f),
                selected: f == selected,
                onTap: () => onSelected(f),
              ),
            ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final shape = StadiumBorder(
      side: selected ? BorderSide.none : const BorderSide(color: AppColors.chipBorder),
    );
    return Material(
      color: selected ? AppColors.textPrimary : Colors.white,
      shape: shape,
      child: InkWell(
        onTap: onTap,
        customBorder: shape,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: selected ? Colors.white : AppColors.textPrimary,
            ),
          ),
        ),
      ),
    );
  }
}
