import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/staff.dart';
import 'staff_repository.dart';

/// รายชื่อ staff สำหรับหน้า "Who's on shift?"
final staffListProvider = FutureProvider<List<Staff>>(
  (ref) => ref.watch(staffRepositoryProvider).listStaff(),
);

/// staff ที่เลือกไว้ (จำไว้ในเครื่อง เปิด app ใหม่ไม่ต้องเลือกซ้ำ) null = ยังไม่ได้เลือก
final selectedStaffProvider =
    AsyncNotifierProvider<SelectedStaffNotifier, Staff?>(SelectedStaffNotifier.new);

class SelectedStaffNotifier extends AsyncNotifier<Staff?> {
  static const _key = 'selected_staff';

  @override
  Future<Staff?> build() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return null;
    return Staff.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> select(Staff staff) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, jsonEncode(staff.toJson()));
    state = AsyncData(staff);
  }

  /// เปลี่ยนคน (กลับไปหน้าเลือกชื่อ)
  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
    state = const AsyncData<Staff?>(null);
  }
}
