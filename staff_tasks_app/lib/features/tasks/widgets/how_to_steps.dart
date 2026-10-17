import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import '../../../models/task.dart';
import 'action_section.dart';

/// "How to do it" + "Why this task"
class HowToSteps extends StatelessWidget {
  const HowToSteps({super.key, required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    final steps = task.instructionSteps;
    final fallback = task.staffInstructions;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionTitle('How to do it'),
        const SizedBox(height: 16),
        if (steps.isNotEmpty)
          for (var i = 0; i < steps.length; i++)
            _StepTile(number: i + 1, step: steps[i], isLast: i == steps.length - 1)
        else
          Text(
            (fallback == null || fallback.isEmpty) ? 'No instructions for this task.' : fallback,
            style: const TextStyle(fontSize: 15, height: 1.45, color: AppColors.textSecondary),
          ),
        if (task.aiReasoning != null && task.aiReasoning!.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Divider(height: 1, color: Color(0xFFD8D8DC)),
          const SizedBox(height: 16),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 1),
                child: Icon(Icons.info_outline, size: 18, color: AppColors.urgentBadge),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      const TextSpan(
                        text: 'Why this task · ',
                        style: TextStyle(fontWeight: FontWeight.w700, color: AppColors.textPrimary),
                      ),
                      TextSpan(text: task.aiReasoning),
                    ],
                  ),
                  style: const TextStyle(fontSize: 14, height: 1.45, color: AppColors.textSecondary),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({required this.number, required this.step, required this.isLast});

  final int number;
  final InstructionStep step;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Container(
                  width: 26,
                  height: 26,
                  alignment: Alignment.center,
                  decoration: const BoxDecoration(
                    color: AppColors.textPrimary,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    '$number',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(width: 2, color: const Color(0xFFD1D1D6)),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(top: 2, bottom: isLast ? 8 : 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    step.title,
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    step.detail,
                    style: const TextStyle(
                      fontSize: 14,
                      height: 1.4,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
