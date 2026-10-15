import 'package:intl/intl.dart';

import '../models/task.dart';

/// ข้อความสำหรับแสดงผล (ภาษาอังกฤษตามดีไซน์)
const categoryLabels = {
  'MEAT': 'Meat',
  'SEAFOOD': 'Seafood',
  'BAKERY': 'Bakery',
  'DAIRY': 'Dairy',
  'READY_TO_EAT': 'Deli',
  'PRODUCE': 'Produce',
};

/// เช่น ["MEAT", "SEAFOOD"] → "Meat & Seafood"
String zoneLabel(List<String> categories) =>
    categories.map((c) => categoryLabels[c] ?? c).join(' & ');

String roleLabel(String role) => role == 'MANAGER' ? 'Manager' : 'Staff';

/// กะทำงานจากเวลาปัจจุบัน
String currentShiftLabel([DateTime? now]) {
  final hour = (now ?? DateTime.now()).hour;
  if (hour >= 6 && hour < 12) return 'Morning shift';
  if (hour >= 12 && hour < 18) return 'Afternoon shift';
  return 'Night shift';
}

/// ยังไม่มีข้อมูลสาขาใน DB จึงใส่ค่าตายตัวตามดีไซน์
const storeLabel = 'Store 014';

// ---------- หน้า My tasks ----------

/// คำทักทายตามเวลา
String greetingLabel([DateTime? now]) {
  final hour = (now ?? DateTime.now()).hour;
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

/// เวลาแบบ 24 ชม. เช่น 09:30
final hhmm = DateFormat('HH:mm');

const _unitNames = {
  'PACK': ('pack', 'packs'),
  'PIECE': ('pc', 'pcs'),
};

/// เช่น (18, PACK) → "18 packs"
String quantityLabel(int qty, String unit) {
  final names = _unitNames[unit];
  if (names == null) return '$qty ${unit.toLowerCase()}';
  return '$qty ${qty == 1 ? names.$1 : names.$2}';
}

String _pctLabel(double? pct) {
  if (pct == null) return '';
  return pct == pct.roundToDouble() ? '${pct.toInt()}%' : '${pct.toStringAsFixed(1)}%';
}

/// ข้อความในป้ายประเภทงาน เช่น "Markdown 30%"
String actionLabel(Task task) => switch (task.actionType) {
      ActionType.markdown => 'Markdown ${_pctLabel(task.discountPct)}'.trim(),
      ActionType.kitchenRepurpose => 'Kitchen repurpose',
      ActionType.donate => 'Donation',
      ActionType.discard => 'Discard',
    };

/// งานที่ต้องมีคนมารับของ (บริจาค / ทิ้ง) ใช้คำว่า Pickup นอกนั้นใช้ Due
String dueLabel(Task task, DateTime dueBy) {
  final prefix = switch (task.actionType) {
    ActionType.donate || ActionType.discard => 'Pickup',
    _ => 'Due',
  };
  return '$prefix ${hhmm.format(dueBy.toLocal())}';
}

/// บรรทัด lot เช่น "LOT-000004 · MEAT-B · B-01 · 18 packs"
String taskLotLine(Task task) => [
      task.lotId,
      task.lot?.locationAisle,
      task.lot?.locationShelf,
      quantityLabel(task.actionQuantity, task.product?.unitOfMeasure ?? 'PIECE'),
    ].whereType<String>().join(' · ');
