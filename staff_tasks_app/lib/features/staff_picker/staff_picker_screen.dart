import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/labels.dart';
import '../../core/theme.dart';
import '../../models/staff.dart';
import '../../widgets/staff_avatar.dart';
import 'staff_providers.dart';

/// หน้า "Who's on shift?" ให้ staff เลือกชื่อตัวเอง (ไม่มี login)
class StaffPickerScreen extends ConsumerWidget {
  const StaffPickerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: Stack(
        children: [
          const Positioned(top: -170, right: -150, child: _OrangeGlow()),
          SafeArea(
            child: RefreshIndicator(
              color: AppColors.orange,
              onRefresh: () => ref.refresh(staffListProvider.future),
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
                children: [
                  const _Brand(),
                  const SizedBox(height: 40),
                  const Text(
                    "Who's on shift?",
                    style: TextStyle(
                      fontSize: 34,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.8,
                      height: 1.1,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Tap your name to see your tasks.\n$storeLabel · ${currentShiftLabel()}',
                    style: const TextStyle(
                      fontSize: 15,
                      height: 1.4,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 44),
                  const Text(
                    'ALL STAFF',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0.6,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 12),
                  const _StaffCard(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// วงแสงสีส้มไล่สีมุมขวาบน
class _OrangeGlow extends StatelessWidget {
  const _OrangeGlow();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Container(
        width: 480,
        height: 480,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              AppColors.orange.withValues(alpha: 0.9),
              AppColors.orangeSoft.withValues(alpha: 0.5),
              AppColors.background.withValues(alpha: 0),
            ],
            stops: const [0.0, 0.45, 1.0],
          ),
        ),
      ),
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Image.asset('assets/images/logo_mark.png'),
        ),
        const SizedBox(width: 10),
        const Text(
          'No-Waste-Bro',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, letterSpacing: -0.2),
        ),
      ],
    );
  }
}

class _StaffCard extends ConsumerWidget {
  const _StaffCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final staff = ref.watch(staffListProvider);

    final Widget content = staff.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(32),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => _CardMessage(
        message: error is ApiException ? error.message : 'Could not load staff.',
        actionLabel: 'Try again',
        onAction: () => ref.invalidate(staffListProvider),
      ),
      data: (list) => list.isEmpty
          ? const _CardMessage(message: 'No staff on this shift yet.')
          : Column(
              children: [
                for (var i = 0; i < list.length; i++) ...[
                  if (i > 0) const Divider(height: 1, thickness: 1, indent: 74),
                  _StaffRow(
                    staff: list[i],
                    onTap: () => ref.read(selectedStaffProvider.notifier).select(list[i]),
                  ),
                ],
              ],
            ),
    );

    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(24),
      ),
      child: content,
    );
  }
}

class _StaffRow extends StatelessWidget {
  const _StaffRow({required this.staff, required this.onTap});

  final Staff staff;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 14, 14),
          child: Row(
            children: [
              StaffAvatar(name: staff.fullName, imageUrl: staff.imageUrl, size: 44),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      staff.fullName,
                      style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${zoneLabel(staff.responsibleCategories)} · ${roleLabel(staff.role)}',
                      style: const TextStyle(fontSize: 14, color: AppColors.textSecondary),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: AppColors.textSecondary),
            ],
          ),
        ),
      ),
    );
  }
}

class _CardMessage extends StatelessWidget {
  const _CardMessage({required this.message, this.actionLabel, this.onAction});

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textSecondary),
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
