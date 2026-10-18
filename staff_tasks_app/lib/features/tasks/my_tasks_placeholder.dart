import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../models/staff.dart';
import '../../widgets/staff_avatar.dart';
import '../staff_picker/staff_providers.dart';

/// หน้าชั่วคราวหลังเลือก staff (จะแทนด้วยหน้ารายการงานตามดีไซน์)
class MyTasksPlaceholder extends ConsumerWidget {
  const MyTasksPlaceholder({super.key, required this.staff});

  final Staff staff;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                StaffAvatar(name: staff.fullName, imageUrl: staff.imageUrl, size: 72),
                const SizedBox(height: 12),
                Text(
                  staff.fullName,
                  style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                ),
                Text(
                  '${zoneLabel(staff.responsibleCategories)} · ${roleLabel(staff.role)}',
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
                const SizedBox(height: 24),
                const Text(
                  'Task list is coming next.',
                  style: TextStyle(color: AppColors.textSecondary),
                ),
                const SizedBox(height: 24),
                OutlinedButton.icon(
                  onPressed: () => ref.read(selectedStaffProvider.notifier).clear(),
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('Switch staff'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
