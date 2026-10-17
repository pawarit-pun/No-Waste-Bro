import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/task.dart';
import 'task_providers.dart';
import 'task_repository.dart';

/// กดรับ / ปฏิเสธ / ปิดงาน แล้วโหลดหน้ารายละเอียดและรายการงานใหม่
final taskActionsProvider = Provider<TaskActions>(TaskActions.new);

class TaskActions {
  TaskActions(this._ref);
  final Ref _ref;

  TaskRepository get _repo => _ref.read(taskRepositoryProvider);

  void _refresh(String taskId, String staffId) {
    _ref.invalidate(taskDetailProvider(taskId));
    _ref.invalidate(taskListProvider(staffId));
  }

  Future<Task> accept(String taskId, String staffId) async {
    final task = await _repo.accept(taskId, staffId);
    _refresh(taskId, staffId);
    return task;
  }

  Future<Task> reject(String taskId, String staffId, String reason) async {
    final task = await _repo.reject(taskId, staffId, reason);
    _refresh(taskId, staffId);
    return task;
  }

  Future<TaskCompleteResult> complete(String taskId, String staffId, int quantity) async {
    final result = await _repo.complete(taskId, staffId, quantity);
    _refresh(taskId, staffId);
    return result;
  }
}
