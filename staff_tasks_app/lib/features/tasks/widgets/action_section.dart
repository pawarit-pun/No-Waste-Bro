import 'package:flutter/material.dart';

import '../../../core/labels.dart';
import '../../../core/theme.dart';
import '../../../models/task.dart';

/// ส่วนกลางของหน้า Task detail เปลี่ยนตามประเภทงาน
class ActionSection extends StatelessWidget {
  const ActionSection({super.key, required this.task});

  final Task task;

  String get _unit => task.product?.unitOfMeasure ?? 'PIECE';

  @override
  Widget build(BuildContext context) {
    return switch (task.actionType) {
      ActionType.markdown => _markdown(),
      ActionType.kitchenRepurpose => _kitchen(),
      ActionType.donate => _partnerSection('Donation', 'Donate'),
      ActionType.animalFeed ||
      ActionType.compost ||
      ActionType.anaerobicDigestion ||
      ActionType.landfill =>
        _partnerSection('Pickup', 'Hand over'),
      ActionType.discard => _discard(),
    };
  }

  Widget _impactRow() => task.expectedProfitImpact == null
      ? const SizedBox.shrink()
      : DetailRow(label: 'Expected recovery', value: baht(task.expectedProfitImpact!));

  Widget _markdown() {
    final open = task.status == TaskStatus.pending || task.status == TaskStatus.inProgress;
    final remaining = (task.lot?.currentQuantity ?? 0) - task.actionQuantity;
    final unitWord = quantityLabel(1, _unit).split(' ').last;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionTitle('New price'),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text(
              baht(task.originalPrice),
              style: const TextStyle(
                fontSize: 18,
                color: AppColors.textSecondary,
                decoration: TextDecoration.lineThrough,
              ),
            ),
            const SizedBox(width: 12),
            const Icon(Icons.arrow_forward, size: 20, color: AppColors.textSecondary),
            const SizedBox(width: 12),
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(
                  task.newRecommendedPrice == null ? '-' : baht(task.newRecommendedPrice!),
                  style: const TextStyle(
                    fontSize: 38,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -1,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text('/ $unitWord', style: const TextStyle(color: AppColors.textSecondary)),
          ],
        ),
        const SizedBox(height: 12),
        DetailRow(label: 'Apply to', value: quantityLabel(task.actionQuantity, _unit)),
        if (open && remaining > 0)
          DetailRow(
            label: 'Remaining ${quantityLabel(remaining, _unit)}',
            value: 'Sell at regular price',
          ),
        _impactRow(),
      ],
    );
  }

  Widget _kitchen() {
    final recipe = task.recipe;
    final batches = task.batchCount ?? 1;
    final outputPerBatch = (recipe?['output_quantity'] as num?)?.toDouble();
    final prepMins = (recipe?['estimated_prep_time_mins'] as num?)?.toInt();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionTitle('Kitchen plan'),
        const SizedBox(height: 8),
        if (recipe != null) DetailRow(label: 'Recipe', value: recipe['name'] as String),
        if (recipe?['department_name'] != null)
          DetailRow(label: 'Kitchen', value: recipe!['department_name'] as String),
        DetailRow(label: 'Use', value: quantityLabel(task.actionQuantity, _unit)),
        DetailRow(label: 'Batches', value: '$batches'),
        if (outputPerBatch != null)
          DetailRow(label: 'Output', value: '${(outputPerBatch * batches).floor()} items'),
        if (prepMins != null)
          DetailRow(label: 'Prep time', value: durationLabel(prepMins * batches)),
        _impactRow(),
      ],
    );
  }

  /// ชื่อ partner, ช่วงเวลารับของ, ผู้ติดต่อ (ว่าง = ไม่มี partner)
  List<Widget> _partnerRows() {
    final partner = task.partner;
    if (partner == null) return const [];
    String? time(String key) => (partner[key] as String?)?.substring(0, 5);
    final start = time('pickup_time_start');
    final end = time('pickup_time_end');
    final contact = [partner['contact_name'], partner['contact_phone']]
        .whereType<String>()
        .join(' · ');
    return [
      DetailRow(label: 'Partner', value: partner['name'] as String),
      if (start != null && end != null) DetailRow(label: 'Pickup window', value: '$start–$end'),
      if (contact.isNotEmpty) DetailRow(label: 'Contact', value: contact),
    ];
  }

  /// บริจาค / ส่ง partner ไปกำจัด
  Widget _partnerSection(String title, String quantityLabelText) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionTitle(title),
          const SizedBox(height: 8),
          DetailRow(label: quantityLabelText, value: quantityLabel(task.actionQuantity, _unit)),
          ..._partnerRows(),
        ],
      );

  /// ทิ้งเองในร้าน (ถ้าข้อมูลเก่ามี partner ก็แสดงด้วย)
  Widget _discard() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionTitle('Discard'),
          const SizedBox(height: 8),
          DetailRow(label: 'Discard', value: quantityLabel(task.actionQuantity, _unit)),
          ..._partnerRows(),
        ],
      );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, letterSpacing: -0.3),
      );
}

/// แถว label ซ้าย / ค่าขวา มีเส้นคั่นด้านบน
class DetailRow extends StatelessWidget {
  const DetailRow({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: Color(0xFFD8D8DC))),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(label, style: const TextStyle(fontSize: 15, color: AppColors.textPrimary)),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}
