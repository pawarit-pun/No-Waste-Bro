import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// ชีตเลือกจำนวนที่ทำได้จริง คืนค่าจำนวน (null = ยกเลิก)
Future<int?> showCompleteSheet(BuildContext context, Task task) => showModalBottomSheet<int>(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (_) => _CompleteSheet(task: task),
    );

class _CompleteSheet extends StatefulWidget {
  const _CompleteSheet({required this.task});

  final Task task;

  @override
  State<_CompleteSheet> createState() => _CompleteSheetState();
}

class _CompleteSheetState extends State<_CompleteSheet> {
  late int _qty = widget.task.actionQuantity;

  int get _max => widget.task.actionQuantity;

  @override
  Widget build(BuildContext context) {
    final unit = widget.task.product?.unitOfMeasure ?? 'PIECE';
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 20, 20, MediaQuery.paddingOf(context).bottom + 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Complete task', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          const Text(
            'How many did you actually handle?',
            style: TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: 20),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _RoundButton(
                icon: Icons.remove,
                onTap: _qty > 0 ? () => setState(() => _qty--) : null,
              ),
              SizedBox(
                width: 140,
                child: Column(
                  children: [
                    Text(
                      '$_qty',
                      style: const TextStyle(fontSize: 44, fontWeight: FontWeight.w800),
                    ),
                    Text(
                      'of ${quantityLabel(_max, unit)}',
                      style: const TextStyle(color: AppColors.textSecondary),
                    ),
                  ],
                ),
              ),
              _RoundButton(
                icon: Icons.add,
                onTap: _qty < _max ? () => setState(() => _qty++) : null,
              ),
            ],
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            height: 54,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.textPrimary,
                shape: const StadiumBorder(),
              ),
              onPressed: () => Navigator.of(context).pop(_qty),
              child: const Text(
                'Complete',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({required this.icon, this.onTap});

  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.background,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: SizedBox(
          width: 52,
          height: 52,
          child: Icon(icon, color: onTap == null ? AppColors.chipBorder : AppColors.textPrimary),
        ),
      ),
    );
  }
}
