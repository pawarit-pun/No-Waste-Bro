import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/staff.dart';
import 'staff_repository.dart';

/// รายชื่อ staff สำหรับหน้า "Who's on shift?"
final staffListProvider = FutureProvider<List<Staff>>(
  (ref) => ref.watch(staffRepositoryProvider).listStaff(),
);

/// staff ที่เลือกในรอบนี้ (ไม่จำข้ามการเปิด app → เปิดใหม่ต้องเลือกทุกครั้ง) null = ยังไม่ได้เลือก
final selectedStaffProvider =
    AsyncNotifierProvider<SelectedStaffNotifier, Staff?>(SelectedStaffNotifier.new);

class SelectedStaffNotifier extends AsyncNotifier<Staff?> {
  @override
  Future<Staff?> build() async => null;

  void select(Staff staff) => state = AsyncData(staff);

  /// เปลี่ยนคน (กลับไปหน้าเลือกชื่อ)
  void clear() => state = const AsyncData<Staff?>(null);
}
