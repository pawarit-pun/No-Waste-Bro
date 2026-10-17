import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../models/task.dart';

final taskRepositoryProvider =
    Provider<TaskRepository>((ref) => TaskRepository(ref.watch(dioProvider)));

class TaskRepository {
  TaskRepository(this._dio);
  final Dio _dio;

  /// GET /tasks?staff_id=&status= (ค่าเริ่มต้น = งานที่ยังไม่จบ)
  Future<List<Task>> listTasks(
    String staffId, {
    List<TaskStatus> statuses = const [TaskStatus.pending, TaskStatus.inProgress],
  }) =>
      guardApi(() async {
        final res = await _dio.get<List<dynamic>>(
          '/tasks',
          queryParameters: {
            'staff_id': staffId,
            'status': statuses.map((s) => s.value).toList(),
          },
          options: Options(listFormat: ListFormat.multi), // status=A&status=B
        );
        return res.data!.map((e) => Task.fromJson(e as Map<String, dynamic>)).toList();
      });

  /// GET /tasks/{id}
  Future<Task> getTask(String taskId) => guardApi(() async {
        final res = await _dio.get<Map<String, dynamic>>('/tasks/$taskId');
        return Task.fromJson(res.data!);
      });

  /// POST /tasks/{id}/accept → IN_PROGRESS
  Future<Task> accept(String taskId, String staffId) => guardApi(() async {
        final res = await _dio.post<Map<String, dynamic>>(
          '/tasks/$taskId/accept',
          data: {'staff_id': staffId},
        );
        return Task.fromJson(res.data!);
      });

  /// POST /tasks/{id}/reject → REJECTED (ต้องมีเหตุผล)
  Future<Task> reject(String taskId, String staffId, String reason) => guardApi(() async {
        final res = await _dio.post<Map<String, dynamic>>(
          '/tasks/$taskId/reject',
          data: {'staff_id': staffId, 'rejection_reason': reason},
        );
        return Task.fromJson(res.data!);
      });

  /// POST /tasks/{id}/complete → COMPLETED + อัปเดตสต็อก
  Future<TaskCompleteResult> complete(String taskId, String staffId, int actualQuantity) =>
      guardApi(() async {
        final res = await _dio.post<Map<String, dynamic>>(
          '/tasks/$taskId/complete',
          data: {'staff_id': staffId, 'actual_quantity_handled': actualQuantity},
        );
        return TaskCompleteResult.fromJson(res.data!);
      });
}
