import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../models/staff.dart';
import '../../models/task.dart';
import '../../widgets/staff_avatar.dart';
import '../staff_picker/staff_providers.dart';
import 'task_providers.dart';
import 'widgets/filter_chips.dart';
import 'widgets/task_card.dart';
import 'widgets/urgent_banner.dart';

/// หน้าแรกหลังเลือก staff: งานของคนนี้ แยกตามสถานะ
/// อัปเดตเองผ่าน Realtime และดึงลงเพื่อรีเฟรชได้
class MyTasksScreen extends ConsumerWidget {
  const MyTasksScreen({super.key, required this.staff});

  final Staff staff;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = taskListProvider(staff.staffId);
    final tasks = ref.watch(provider);
    final filter = ref.watch(taskFilterProvider);
    final topInset = MediaQuery.paddingOf(context).top;

    final List<Widget> body = tasks.when(
      skipLoadingOnReload: true,
      loading: () => const [
        Padding(
          padding: EdgeInsets.only(top: 80),
          child: Center(child: CircularProgressIndicator()),
        ),
      ],
      error: (error, _) => [
        const SizedBox(height: 24),
        _MessageCard(
          message: error is ApiException ? error.message : 'Could not load tasks.',
          actionLabel: 'Try again',
          onAction: () => ref.invalidate(provider),
        ),
      ],
      data: (list) => _content(ref, list, filter),
    );

    return Scaffold(
      body: RefreshIndicator(
        color: AppColors.orange,
        edgeOffset: topInset,
        onRefresh: () => ref.refresh(provider.future),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: EdgeInsets.fromLTRB(20, topInset + 16, 20, 32),
          children: [
            _Header(staff: staff, topInset: topInset),
            const SizedBox(height: 20),
            ...body,
          ],
        ),
      ),
    );
  }

  List<Widget> _content(WidgetRef ref, List<Task> list, TaskFilter filter) {
    final urgent = list.where(isUrgentTask).toList();
    final visible = list.where(filter.matches).toList();
    return [
      if (urgent.isNotEmpty) ...[
        UrgentBanner(tasks: urgent),
        const SizedBox(height: 16),
      ],
      TaskFilterChips(
        total: list.length,
        selected: filter,
        onSelected: ref.read(taskFilterProvider.notifier).select,
      ),
      const SizedBox(height: 24),
      const Text(
        'Tasks',
        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: -0.3),
      ),
      const SizedBox(height: 12),
      if (visible.isEmpty)
        _MessageCard(message: _emptyMessage(filter))
      else
        for (final task in visible)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            // TODO: เปิดหน้ารายละเอียดงานเมื่อได้ดีไซน์
            child: TaskCard(task: task),
          ),
    ];
  }

  String _emptyMessage(TaskFilter filter) => switch (filter) {
        TaskFilter.all => 'No tasks yet.\nNew tasks from the AI will show up here.',
        TaskFilter.pending => 'No pending tasks.',
        TaskFilter.inProgress => 'Nothing in progress.',
        TaskFilter.done => 'No tasks completed today.',
      };
}

/// คำทักทาย + ชื่อ + รูป บนพื้นแสงสีส้ม (แสงเลื่อนไปพร้อมเนื้อหา)
class _Header extends StatelessWidget {
  const _Header({required this.staff, required this.topInset});

  final Staff staff;
  final double topInset;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned(top: -topInset - 316, left: -140, child: const _HeaderGlow()),
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    greetingLabel(),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    staff.fullName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.6,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            _AvatarMenu(staff: staff),
          ],
        ),
      ],
    );
  }
}

class _HeaderGlow extends StatelessWidget {
  const _HeaderGlow();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Container(
        width: 640,
        height: 640,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              const Color(0xFFC2410C),
              AppColors.orange.withValues(alpha: 0.95),
              AppColors.orangeSoft.withValues(alpha: 0.55),
              AppColors.background.withValues(alpha: 0),
            ],
            stops: const [0.0, 0.5, 0.75, 1.0],
          ),
        ),
      ),
    );
  }
}

/// กดรูปโปรไฟล์ → เมนูเปลี่ยน staff
class _AvatarMenu extends ConsumerWidget {
  const _AvatarMenu({required this.staff});

  final Staff staff;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return PopupMenuButton<String>(
      tooltip: 'Account',
      position: PopupMenuPosition.under,
      onSelected: (_) {
        ref.read(taskFilterProvider.notifier).select(TaskFilter.all);
        ref.read(selectedStaffProvider.notifier).clear();
      },
      itemBuilder: (_) => const [
        PopupMenuItem(
          value: 'switch',
          child: Row(
            children: [
              Icon(Icons.swap_horiz, size: 20),
              SizedBox(width: 10),
              Text('Switch staff'),
            ],
          ),
        ),
      ],
      child: Container(
        padding: const EdgeInsets.all(3),
        decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
        child: StaffAvatar(name: staff.fullName, imageUrl: staff.imageUrl, size: 54),
      ),
    );
  }
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.message, this.actionLabel, this.onAction});

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textSecondary, height: 1.4),
          ),
          if (actionLabel != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ],
      ),
    );
  }
}
