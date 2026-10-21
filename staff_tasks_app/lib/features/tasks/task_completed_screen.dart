import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../models/task.dart';
import 'task_start_times.dart';

/// หน้าสรุปหลังกด Complete สำเร็จ (เปิดแทนหน้า Task detail)
/// timeline Assigned → Started → Completed + ผลของงานตาม action type
class TaskCompletedScreen extends ConsumerWidget {
  const TaskCompletedScreen({
    super.key,
    required this.task,
    required this.result,
    required this.handled,
  });

  /// task จากหน้า detail (มี product / partner / recipe ครบ)
  final Task task;

  /// ผลของ POST /complete (completed_at, effects)
  final TaskCompleteResult result;

  /// จำนวนที่กรอกในชีต Complete
  final int handled;

  String get _unit => task.product?.unitOfMeasure ?? 'PIECE';

  int get _handled => result.task.actualQuantityHandled ?? handled;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final startedAt = ref.watch(taskStartTimeProvider(task.taskId)).value;
    final completedAt = (result.task.completedAt ?? DateTime.now()).toLocal();
    final assignedAt = task.createdAt.toLocal();
    final minutes = completedAt.difference(startedAt ?? assignedAt).inMinutes;
    final took = minutes < 1 ? '<1 min' : durationLabel(minutes);

    return Scaffold(
      body: Stack(
        children: [
          const Positioned(top: 0, left: 0, right: 0, child: Center(child: _Glow())),
          SafeArea(
            child: Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(24, 104, 24, 24),
                    children: [
                      const Center(child: _CheckCircle()),
                      const SizedBox(height: 28),
                      const Text(
                        'Task completed',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 30,
                          fontWeight: FontWeight.w800,
                          letterSpacing: -0.8,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '${task.product?.name ?? task.productId ?? '-'} · ${actionLabel(task)}',
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 15, color: AppColors.textSecondary),
                      ),
                      const SizedBox(height: 36),
                      _TimelineRow(label: 'Assigned', time: hhmm.format(assignedAt)),
                      if (startedAt != null)
                        _TimelineRow(label: 'Started', time: hhmm.format(startedAt)),
                      _TimelineRow(
                        label: 'Completed · $took',
                        time: hhmm.format(completedAt),
                        isLast: true,
                      ),
                      const SizedBox(height: 22),
                      const Divider(height: 1, thickness: 1, color: AppColors.divider),
                      for (final (label, value) in _summaryRows())
                        _SummaryRow(label: label, value: value),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
                  child: SizedBox(
                    width: double.infinity,
                    height: 56,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.textPrimary,
                        foregroundColor: Colors.white,
                        shape: const StadiumBorder(),
                      ),
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            'Back to inbox',
                            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                          ),
                          SizedBox(width: 10),
                          Icon(Icons.arrow_forward, size: 20),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// lot ที่ POST /complete สร้างขึ้น ตามเหตุผล (MARKDOWN_SPLIT / KITCHEN_OUTPUT)
  Map<String, dynamic>? _createdLot(String reason) {
    final created = result.effects['lots_created'] as List? ?? const [];
    for (final lot in created) {
      if (lot is Map && lot['reason'] == reason) return Map<String, dynamic>.from(lot);
    }
    return null;
  }

  /// แถวสรุปผล เปลี่ยนตาม action type
  List<(String, String)> _summaryRows() {
    final handledText = quantityLabel(_handled, _unit);
    final rows = <(String, String)>[];

    switch (task.actionType) {
      case ActionType.markdown:
        final lot = _createdLot('MARKDOWN_SPLIT');
        final price = (lot?['current_selling_price'] as num?) ?? task.newRecommendedPrice;
        final unitWord = quantityLabel(1, _unit).split(' ').last;
        rows.add(('Labels applied', handledText));
        if (price != null) rows.add(('New price', '${baht(price)} / $unitWord'));
        if (lot?['lot_id'] != null) rows.add(('New lot', '${lot!['lot_id']}'));
      case ActionType.kitchenRepurpose:
        final lot = _createdLot('KITCHEN_OUTPUT');
        rows.add(('Used', handledText));
        if (task.recipe?['name'] != null) rows.add(('Recipe', '${task.recipe!['name']}'));
        if (lot?['quantity'] != null) rows.add(('Items made', '${lot!['quantity']} items'));
        if (lot?['lot_id'] != null) rows.add(('New lot', '${lot!['lot_id']}'));
      case ActionType.donate ||
            ActionType.animalFeed ||
            ActionType.compost ||
            ActionType.anaerobicDigestion ||
            ActionType.landfill:
        rows.add(('Handed over', handledText));
        if (task.partner?['name'] != null) rows.add(('Partner', '${task.partner!['name']}'));
      case ActionType.discard:
        rows.add(('Discarded', handledText));
    }

    final planned = task.actionQuantity;
    if (_handled < planned) {
      rows.add(('Not handled', quantityLabel(planned - _handled, _unit)));
    }

    // คิดตามสัดส่วนของจำนวนที่ทำได้จริง
    final impact = task.expectedProfitImpact;
    if (impact != null && planned > 0) {
      rows.add(('Expected recovery', baht(impact * _handled / planned)));
    }
    return rows;
  }
}

/// แสงสีส้มด้านหลังวงกลมเครื่องหมายถูก
class _Glow extends StatelessWidget {
  const _Glow();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Container(
        width: 520,
        height: 520,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              AppColors.orange.withValues(alpha: 0.75),
              AppColors.orangeSoft.withValues(alpha: 0.4),
              AppColors.background.withValues(alpha: 0),
            ],
            stops: const [0.0, 0.4, 1.0],
          ),
        ),
      ),
    );
  }
}

class _CheckCircle extends StatelessWidget {
  const _CheckCircle();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 96,
      height: 96,
      decoration: const BoxDecoration(color: AppColors.textPrimary, shape: BoxShape.circle),
      child: const Icon(Icons.check_rounded, color: Colors.white, size: 48),
    );
  }
}

/// แถว timeline: จุด + เส้นเชื่อม | ชื่อขั้น | เวลา
/// แถวสุดท้าย (Completed) จุดสีส้มและตัวหนา
class _TimelineRow extends StatelessWidget {
  const _TimelineRow({required this.label, required this.time, this.isLast = false});

  final String label;
  final String time;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontSize: 15,
      fontWeight: isLast ? FontWeight.w700 : FontWeight.w400,
      color: AppColors.textPrimary,
    );
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 14,
            child: Column(
              children: [
                const SizedBox(height: 4),
                Container(
                  width: 14,
                  height: 14,
                  decoration: BoxDecoration(
                    color: isLast ? AppColors.orange : AppColors.textPrimary,
                    shape: BoxShape.circle,
                  ),
                ),
                if (!isLast)
                  Expanded(child: Container(width: 2, color: AppColors.textPrimary)),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 14),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: Text(label, style: style)),
                  Text(
                    time,
                    style: style.copyWith(
                      color: isLast ? AppColors.textPrimary : AppColors.textSecondary,
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

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.divider)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontSize: 14, color: AppColors.textSecondary),
            ),
          ),
          const SizedBox(width: 12),
          Text(value, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}
