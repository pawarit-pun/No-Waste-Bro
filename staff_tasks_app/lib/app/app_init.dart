import 'package:firebase_core/firebase_core.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/config.dart';
import '../features/staff_picker/staff_providers.dart';

/// เวลาขั้นต่ำที่แสดงหน้า loading (กันโลโก้กะพริบหายเร็วเกินไป)
const _minSplashDuration = Duration(milliseconds: 1500);

bool _supabaseReady = false;

/// เตรียม app ทั้งหมดระหว่างแสดงหน้า loading
/// กดลองใหม่ได้ ถ้าขั้นตอนไหนพัง (ขั้นที่สำเร็จแล้วจะไม่ทำซ้ำ)
final appInitProvider = FutureProvider<void>((ref) async {
  final minDelay = Future<void>.delayed(_minSplashDuration);

  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp(); // ติดตั้งไว้เผื่อใช้ทีหลัง (ยังไม่ได้ใช้)
  }
  if (!_supabaseReady) {
    await Supabase.initialize(
      url: AppConfig.supabaseUrl,
      anonKey: AppConfig.supabasePublishableKey, // ใช้เฉพาะ Realtime
    );
    _supabaseReady = true;
  }
  await initializeDateFormatting('th');
  await ref.read(selectedStaffProvider.future); // staff ที่เคยเลือกไว้ในเครื่อง

  await minDelay;
});
