import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../models/staff.dart';

final staffRepositoryProvider =
    Provider<StaffRepository>((ref) => StaffRepository(ref.watch(dioProvider)));

class StaffRepository {
  StaffRepository(this._dio);
  final Dio _dio;

  /// GET /staff?role=STAFF → พนักงานหน้าร้านที่ active
  Future<List<Staff>> listStaff({String role = 'STAFF'}) => guardApi(() async {
        final res = await _dio.get<List<dynamic>>('/staff', queryParameters: {'role': role});
        return res.data!.map((e) => Staff.fromJson(e as Map<String, dynamic>)).toList();
      });
}
