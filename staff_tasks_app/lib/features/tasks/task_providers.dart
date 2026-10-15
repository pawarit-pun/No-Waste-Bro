import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../models/task.dart';
import 'task_repository.dart';

/// ฟัง Supabase Realtime ของ task ที่มอบหมายให้ staff คนนี้
/// ทุกครั้งที่มี event (สร้าง task ใหม่ / เปลี่ยนสถานะ) stream จะส่งตัวนับเพิ่มขึ้น 1
/// ใช้ event เป็นแค่สัญญาณ ข้อมูลจริงโหลดจาก API เสมอ
/// ปิดการฟังเองเมื่อไม่มีหน้าจอไหนใช้ (autoDispose)
final taskEventsProvider = StreamProvider.autoDispose.family<int, String>((ref, staffId) {
  final client = Supabase.instance.client;
  final controller = StreamController<int>();
  var count = 0;

  final channel = client
      .channel('tasks-$staffId')
      .onPostgresChanges(
        event: PostgresChangeEvent.all,
        schema: 'public',
        table: 'ai_recommended_tasks',
        filter: PostgresChangeFilter(
          type: PostgresChangeFilterType.eq,
          column: 'assigned_staff_id',
          value: staffId,
        ),
        callback: (_) => controller.add(++count),
      )
      .subscribe();

  ref.onDispose(() {
    client.removeChannel(channel);
    controller.close();
  });
  return controller.stream;
});

/// งานของ staff คนหนึ่งสำหรับหน้า My tasks
/// = งานที่ยังไม่จบ (PENDING, IN_PROGRESS เรียงตาม priority → due จาก API)
///   ต่อด้วยงานที่เสร็จวันนี้ (ล่าสุดก่อน) ไม่แสดงงานที่ถูก reject
/// โหลดใหม่เองทุกครั้งที่ taskEventsProvider มี event
final taskListProvider = FutureProvider.autoDispose.family<List<Task>, String>((ref, staffId) async {
  ref.watch(taskEventsProvider(staffId));
  final tasks = await ref.watch(taskRepositoryProvider).listTasks(
    staffId,
    statuses: const [TaskStatus.pending, TaskStatus.inProgress, TaskStatus.completed],
  );

  final now = DateTime.now();
  bool isToday(DateTime? d) {
    if (d == null) return false;
    final local = d.toLocal();
    return local.year == now.year && local.month == now.month && local.day == now.day;
  }

  final open = tasks.where((t) => t.status != TaskStatus.completed).toList();
  final doneToday = tasks
      .where((t) => t.status == TaskStatus.completed && isToday(t.completedAt))
      .toList()
    ..sort((a, b) => b.completedAt!.compareTo(a.completedAt!));
  return [...open, ...doneToday];
});

/// งานด่วน = ยังไม่เสร็จ, priority 1 และ due วันนี้ (หรือเลยกำหนด / ไม่มี due)
bool isUrgentTask(Task task) {
  if (task.priority != 1 || task.status == TaskStatus.completed) return false;
  final due = task.dueBy?.toLocal();
  if (due == null) return true;
  final now = DateTime.now();
  return due.isBefore(DateTime(now.year, now.month, now.day + 1));
}

/// แท็บกรองในหน้า My tasks
enum TaskFilter {
  all,
  pending,
  inProgress,
  done;

  bool matches(Task task) => switch (this) {
        TaskFilter.all => true,
        TaskFilter.pending => task.status == TaskStatus.pending,
        TaskFilter.inProgress => task.status == TaskStatus.inProgress,
        TaskFilter.done => task.status == TaskStatus.completed,
      };
}

final taskFilterProvider =
    NotifierProvider<TaskFilterNotifier, TaskFilter>(TaskFilterNotifier.new);

class TaskFilterNotifier extends Notifier<TaskFilter> {
  @override
  TaskFilter build() => TaskFilter.all;

  void select(TaskFilter filter) => state = filter;
}

/// รายละเอียด task
final taskDetailProvider = FutureProvider.autoDispose.family<Task, String>(
  (ref, taskId) => ref.watch(taskRepositoryProvider).getTask(taskId),
);
