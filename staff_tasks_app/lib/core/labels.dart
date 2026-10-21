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

String percentLabel(double? pct) {
  if (pct == null) return '';
  return pct == pct.roundToDouble() ? '${pct.toInt()}%' : '${pct.toStringAsFixed(1)}%';
}

/// ข้อความในป้ายประเภทงาน เช่น "Markdown 30%"
String actionLabel(Task task) => switch (task.actionType) {
      ActionType.markdown => 'Markdown ${percentLabel(task.discountPct)}'.trim(),
      ActionType.kitchenRepurpose => 'Kitchen repurpose',
      ActionType.donate => 'Donation',
      ActionType.animalFeed => 'Animal feed pickup',
      ActionType.compost => 'Compost pickup',
      ActionType.anaerobicDigestion => 'Biogas pickup',
      ActionType.landfill => 'Landfill pickup',
      ActionType.discard => 'Discard',
    };

/// ชื่อหัวกลุ่มในหน้า My tasks (ไม่มี % ต่อท้ายแบบ actionLabel)
String actionGroupLabel(ActionType type) => switch (type) {
      ActionType.markdown => 'Markdown',
      ActionType.kitchenRepurpose => 'Kitchen repurpose',
      ActionType.donate => 'Donation',
      ActionType.animalFeed => 'Animal feed',
      ActionType.compost => 'Compost',
      ActionType.anaerobicDigestion => 'Biogas',
      ActionType.landfill => 'Landfill',
      ActionType.discard => 'Discard',
    };

/// ป้าย priority บนการ์ด เช่น 1 → "P1"
String priorityLabel(int priority) => 'P$priority';

/// งานที่ partner มารับของ (บริจาค / อาหารสัตว์ / ปุ๋ยหมัก / ก๊าซชีวภาพ / ฝังกลบ) ใช้คำว่า Pickup นอกนั้นใช้ Due
String dueLabel(Task task, DateTime dueBy) {
  final prefix = task.actionType.usesPartner ? 'Pickup' : 'Due';
  final due = dueBy.toLocal();
  final now = DateTime.now();
  final today = due.year == now.year && due.month == now.month && due.day == now.day;
  // วันอื่นใส่ชื่อวันด้วย เช่น "Pickup Fri 09:00"
  return today
      ? '$prefix ${hhmm.format(due)}'
      : '$prefix ${DateFormat('EEE').format(due)} ${hhmm.format(due)}';
}

/// บรรทัด lot เช่น "LOT-000004 · MEAT-B · B-01 · 18 packs"
String taskLotLine(Task task) => [
      task.lotId,
      task.lot?.locationAisle,
      task.lot?.locationShelf,
      quantityLabel(task.actionQuantity, task.product?.unitOfMeasure ?? 'PIECE'),
    ].whereType<String>().join(' · ');

/// หัวการ์ด: ชื่อสินค้า (งานครัวต่อท้ายด้วยชื่อสูตร เช่น "กล้วยหอม 1kg → เค้กกล้วยหอม")
String taskTitle(Task task) {
  final product = task.product?.name ?? task.productId ?? '-';
  final recipe = task.recipe?['name'] as String?;
  return recipe == null ? product : '$product → $recipe';
}

// ---------- หน้า Task detail ----------

String statusLabel(TaskStatus status) => switch (status) {
      TaskStatus.pending => 'Pending',
      TaskStatus.inProgress => 'In progress',
      TaskStatus.completed => 'Completed',
      TaskStatus.rejected => 'Rejected',
    };

/// LOW / MEDIUM / HIGH / CRITICAL → "High risk"
String riskLabel(String level) => switch (level) {
      'CRITICAL' => 'Critical risk',
      'HIGH' => 'High risk',
      'MEDIUM' => 'Medium risk',
      _ => 'Low risk',
    };

final _money = NumberFormat('#,##0.00');

/// 31.15 → "฿31.15"
String baht(num value) => '฿${_money.format(value)}';

final _dayMonth = DateFormat('EEE d MMM');

/// "Due today 16:00" / "Due tomorrow 09:00" / "Due Fri 16 Oct 09:00"
String dueDayLabel(DateTime dueBy, [DateTime? now]) {
  final due = dueBy.toLocal();
  final today = now ?? DateTime.now();
  final days = DateTime(due.year, due.month, due.day)
      .difference(DateTime(today.year, today.month, today.day))
      .inDays;
  final day = switch (days) {
    0 => 'today',
    1 => 'tomorrow',
    -1 => 'yesterday',
    _ => _dayMonth.format(due),
  };
  return 'Due $day ${hhmm.format(due)}';
}

/// "expires Tue 13 Oct" (DB เก็บแค่วันที่)
String expiresLabel(DateTime date) => 'expires ${_dayMonth.format(date)}';

/// 180 → "3 h", 75 → "1 h 15 min", 45 → "45 min"
String durationLabel(int minutes) {
  final h = minutes ~/ 60;
  final m = minutes % 60;
  if (h == 0) return '$m min';
  return m == 0 ? '$h h' : '$h h $m min';
}
