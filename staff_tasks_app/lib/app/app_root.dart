import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/splash/splash_screen.dart';
import '../features/staff_picker/staff_picker_screen.dart';
import '../features/staff_picker/staff_providers.dart';
import '../features/tasks/my_tasks_screen.dart';
import 'app_init.dart';

/// เลือกหน้าที่จะแสดงจากสถานะของ app
/// loading → Splash, ยังไม่เลือก staff → Who's on shift?, เลือกแล้ว → หน้างาน
class AppRoot extends ConsumerWidget {
  const AppRoot({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final init = ref.watch(appInitProvider);

    final Widget page;
    if (init.hasError && !init.isLoading) {
      page = SplashScreen(
        key: const ValueKey('splash-error'),
        errorMessage: 'Something went wrong while starting the app.',
        onRetry: () => ref.invalidate(appInitProvider),
      );
    } else if (!init.hasValue) {
      page = const SplashScreen(key: ValueKey('splash'));
    } else {
      final staff = ref.watch(selectedStaffProvider).value;
      page = staff == null
          ? const StaffPickerScreen(key: ValueKey('picker'))
          : MyTasksScreen(key: ValueKey('tasks-${staff.staffId}'), staff: staff);
    }

    return AnimatedSwitcher(duration: const Duration(milliseconds: 300), child: page);
  }
}
