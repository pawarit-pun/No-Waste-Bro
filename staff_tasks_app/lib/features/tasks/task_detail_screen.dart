import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../models/task.dart';
import 'task_actions.dart';
import 'task_completed_screen.dart';
import 'task_providers.dart';
import 'widgets/action_section.dart';
import 'widgets/complete_sheet.dart';
import 'widgets/detail_hero.dart';
import 'widgets/how_to_steps.dart';
import 'widgets/reject_sheet.dart';
import 'widgets/task_action_bar.dart';

/// หน้ารายละเอียดงาน (GET /tasks/{id}) + ปุ่ม Start / Complete / Reject
class TaskDetailScreen extends ConsumerStatefulWidget {
  const TaskDetailScreen({super.key, required this.taskId, required this.staffId});

  final String taskId;
  final String staffId;

  @override
  ConsumerState<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends ConsumerState<TaskDetailScreen> {
  bool _busy = false;

  TaskActions get _actions => ref.read(taskActionsProvider);

  void _toast(String message, {bool error = false}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(message),
        backgroundColor: error ? AppColors.urgent : AppColors.textPrimary,
        behavior: SnackBarBehavior.floating,
      ));
  }

  /// รันคำสั่ง แสดง loading บนปุ่ม และแสดง error เป็น snackbar
  Future<T?> _run<T>(Future<T> Function() action) async {
    setState(() => _busy = true);
    try {
      return await action();
    } on ApiException catch (e) {
      if (mounted) _toast(e.message, error: true);
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _start() async {
    final task = await _run(() => _actions.accept(widget.taskId, widget.staffId));
    if (task != null && mounted) _toast('Task started');
  }

  Future<void> _complete(Task task) async {
    final qty = await showCompleteSheet(context, task);
    if (qty == null || !mounted) return;
    final result = await _run(() => _actions.complete(widget.taskId, widget.staffId, qty));
    if (result != null && mounted) {
      // แทนหน้า detail ด้วยหน้าสรุป → กด Back to inbox แล้วกลับหน้า My tasks
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => TaskCompletedScreen(task: task, result: result, handled: qty),
        ),
      );
    }
  }

  Future<void> _reject() async {
    final reason = await showRejectSheet(context);
    if (reason == null || !mounted) return;
    final task = await _run(() => _actions.reject(widget.taskId, widget.staffId, reason));
    if (task != null && mounted) {
      _toast('Task rejected');
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = taskDetailProvider(widget.taskId);
    final value = ref.watch(provider);
    final task = value.value;

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _TopBar(status: task?.status),
            Expanded(
              child: value.when(
                skipLoadingOnReload: true,
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (error, _) => _ErrorView(
                  message: error is ApiException ? error.message : 'Could not load this task.',
                  onRetry: () => ref.invalidate(provider),
                ),
                data: (task) => RefreshIndicator(
                  color: AppColors.orange,
                  onRefresh: () => ref.refresh(provider.future),
                  child: ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
                    children: [
                      DetailHero(task: task),
                      const SizedBox(height: 28),
                      ActionSection(task: task),
                      const SizedBox(height: 28),
                      HowToSteps(task: task),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: task == null
          ? null
          : TaskActionBar(
              task: task,
              busy: _busy,
              onReject: _reject,
              onStart: _start,
              onComplete: () => _complete(task),
            ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({this.status});

  final TaskStatus? status;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
      child: Row(
        children: [
          Material(
            color: AppColors.surface,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: () => Navigator.of(context).maybePop(),
              child: const SizedBox(
                width: 44,
                height: 44,
                child: Icon(Icons.arrow_back, color: AppColors.textPrimary),
              ),
            ),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Text(
              'Task detail',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
            ),
          ),
          if (status != null) _StatusPill(status: status!),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.status});

  final TaskStatus status;

  @override
  Widget build(BuildContext context) {
    final color = statusColor(status);
    final Widget mark = switch (status) {
      TaskStatus.pending => Icon(Icons.radio_button_unchecked, size: 13, color: color),
      TaskStatus.inProgress => Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
      TaskStatus.completed => Icon(Icons.check, size: 15, color: color),
      TaskStatus.rejected => Icon(Icons.close, size: 15, color: color),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          mark,
          const SizedBox(width: 6),
          Text(
            statusLabel(status),
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: color),
          ),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 44, color: AppColors.textSecondary),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
          ],
        ),
      ),
    );
  }
}
