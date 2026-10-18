import 'package:flutter/material.dart';

import '../../core/theme.dart';

/// หน้า loading ตอนเปิด app: โลโก้ + วงกลมหมุน
/// ถ้าเตรียม app ไม่สำเร็จ แสดงข้อความ + ปุ่มลองใหม่แทนวงกลมหมุน
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key, this.errorMessage, this.onRetry});

  final String? errorMessage;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Image.asset('assets/images/logo.jpg', width: 260),
                const SizedBox(height: 32),
                if (errorMessage == null)
                  const SizedBox(
                    width: 32,
                    height: 32,
                    child: CircularProgressIndicator(strokeWidth: 3, color: AppColors.orange),
                  )
                else ...[
                  Text(
                    errorMessage!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 15),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: onRetry, child: const Text('Try again')),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
