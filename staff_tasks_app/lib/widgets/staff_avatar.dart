import 'package:flutter/material.dart';

import '../core/theme.dart';

/// รูปโปรไฟล์วงกลม ถ้าไม่มีรูปหรือโหลดไม่ได้ แสดงตัวอักษรแรกของชื่อแทน
class StaffAvatar extends StatelessWidget {
  const StaffAvatar({super.key, required this.name, this.imageUrl, this.size = 44});

  final String name;
  final String? imageUrl;
  final double size;

  @override
  Widget build(BuildContext context) {
    final fallback = _Initials(name: name, size: size);
    final url = imageUrl;
    if (url == null || url.isEmpty) return fallback;
    return ClipOval(
      child: Image.network(
        url,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => fallback,
        loadingBuilder: (_, child, progress) => progress == null ? child : fallback,
      ),
    );
  }
}

class _Initials extends StatelessWidget {
  const _Initials({required this.name, required this.size});

  final String name;
  final double size;

  @override
  Widget build(BuildContext context) {
    final letter = name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase();
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: const BoxDecoration(color: Color(0xFFFFE1CC), shape: BoxShape.circle),
      child: Text(
        letter,
        style: TextStyle(
          fontSize: size * 0.42,
          fontWeight: FontWeight.w700,
          color: AppColors.orange,
        ),
      ),
    );
  }
}
