import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app_root.dart';
import 'core/theme.dart';

/// การเตรียม app (Firebase, Supabase, ข้อมูลในเครื่อง) อยู่ใน appInitProvider
/// ทำระหว่างแสดงหน้า loading แทนการรอก่อน runApp
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: StaffTasksApp()));
}

class StaffTasksApp extends StatelessWidget {
  const StaffTasksApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'No-Waste-Bro',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: const AppRoot(),
    );
  }
}
