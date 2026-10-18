import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config.dart';

/// Dio ตัวเดียวที่ทั้ง app ใช้เรียก FastAPI
final dioProvider = Provider<Dio>((ref) {
  return Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
      headers: {'Content-Type': 'application/json'},
    ),
  );
});

/// Error จาก API ที่แปลงเป็นข้อความภาษาไทยสำหรับแสดงผู้ใช้แล้ว
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.detail});

  /// ข้อความภาษาไทยสำหรับแสดงผู้ใช้
  final String message;

  /// HTTP status (null = ต่อ server ไม่ได้)
  final int? statusCode;

  /// ข้อความจาก server (ภาษาอังกฤษ) ไว้ debug
  final String? detail;

  @override
  String toString() => 'ApiException($statusCode): $message ${detail ?? ''}';

  factory ApiException.fromDio(DioException e) {
    final response = e.response;
    if (response == null) {
      return ApiException(
        'เชื่อมต่อ server ไม่ได้ ตรวจว่าเปิด server ไว้ที่ ${AppConfig.apiBaseUrl}',
        detail: e.message,
      );
    }
    final status = response.statusCode;
    final detail = _detailOf(response.data);
    final message = switch (status) {
      403 => 'งานนี้ไม่ได้มอบหมายให้คุณ',
      404 => 'ไม่พบข้อมูลที่ต้องการ',
      409 => 'สถานะงานเปลี่ยนไปแล้ว กรุณารีเฟรช',
      422 => 'ข้อมูลไม่ถูกต้อง',
      _ => 'เกิดข้อผิดพลาดจาก server ($status)',
    };
    return ApiException(message, statusCode: status, detail: detail);
  }

  /// FastAPI ส่ง {"detail": "..."} หรือ {"detail": [{"msg": ...}]} (validation error)
  static String? _detailOf(Object? data) {
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is List) {
        return detail
            .map((e) => e is Map ? e['msg']?.toString() ?? '' : e.toString())
            .join(', ');
      }
      return detail.toString();
    }
    return null;
  }
}

/// เรียก API แล้วแปลง DioException เป็น ApiException ทุกครั้ง
Future<T> guardApi<T>(Future<T> Function() call) async {
  try {
    return await call();
  } on DioException catch (e) {
    throw ApiException.fromDio(e);
  }
}
