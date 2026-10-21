import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// เวลาที่ staff กด Start งาน เก็บไว้ในเครื่อง (DB ไม่มีคอลัมน์นี้)
/// ใช้แสดงแถว "Started" และระยะเวลาทำงานในหน้า Task completed
/// ถ้ากด Start จากเครื่องอื่น จะไม่มีค่า → หน้า completed ซ่อนแถว Started
class TaskStartTimes {
  TaskStartTimes._();

  static const _prefix = 'task_started_at:';

  /// บันทึกไม่สำเร็จก็ไม่เป็นไร (ไม่ให้กระทบการกด Start)
  static Future<void> save(String taskId, DateTime at) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('$_prefix$taskId', at.toUtc().toIso8601String());
    } catch (_) {}
  }

  static Future<DateTime?> load(String taskId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString('$_prefix$taskId');
      return raw == null ? null : DateTime.parse(raw).toLocal();
    } catch (_) {
      return null;
    }
  }
}

/// เวลาเริ่มงานของ task (null = ไม่มีข้อมูลในเครื่องนี้)
final taskStartTimeProvider = FutureProvider.autoDispose.family<DateTime?, String>(
  (ref, taskId) => TaskStartTimes.load(taskId),
);
