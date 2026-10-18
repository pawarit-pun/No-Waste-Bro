// ทดสอบการอ่าน JSON จาก API (ไม่ต้องเปิด Firebase / Supabase / server)
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:staff_tasks_app/core/api_client.dart';
import 'package:staff_tasks_app/models/staff.dart';
import 'package:staff_tasks_app/models/task.dart';

void main() {
  test('Staff.fromJson อ่าน response ของ GET /staff ได้', () {
    final staff = Staff.fromJson({
      'staff_id': 'STF-003',
      'full_name': 'C Natcha',
      'role': 'STAFF',
      'responsible_categories': ['BAKERY', 'DAIRY'],
      'image_url': null,
      'is_active': true,
    });
    expect(staff.staffId, 'STF-003');
    expect(staff.responsibleCategories, ['BAKERY', 'DAIRY']);
    expect(Staff.fromJson(staff.toJson()).fullName, 'C Natcha');
  });

  test('Task.fromJson อ่าน task + product + lot ได้ (ตัวเลขเป็น int หรือ double ก็ได้)', () {
    final task = Task.fromJson({
      'task_id': 'eeeeeeee-0000-0000-0000-000000000001',
      'task_status': 'IN_PROGRESS',
      'action_type': 'MARKDOWN',
      'action_quantity': 30,
      'priority': 2,
      'original_price': 47.5,
      'discount_pct': 30,
      'new_recommended_price': 33.25,
      'created_at': '2026-10-15T05:00:00+00:00',
      'due_by': null,
      'assigned_staff_id': 'STF-003',
      'product': {
        'product_id': 'DAI-001',
        'name': 'นมสดพาสเจอร์ไรส์ รสจืด 830ml',
        'category': 'DAIRY',
        'unit_of_measure': 'PIECE',
        'image_url': null,
      },
      'lot': {
        'lot_id': 'LOT-000001',
        'current_quantity': 85,
        'expiration_date': '2026-10-14',
        'location_aisle': 'CHILL-A',
        'location_shelf': 'A-01',
      },
      'assigned_staff': {'staff_id': 'STF-003', 'full_name': 'C Natcha', 'image_url': null},
    });
    expect(task.status, TaskStatus.inProgress);
    expect(task.actionType, ActionType.markdown);
    expect(task.discountPct, 30.0);
    expect(task.lot!.location, 'CHILL-A / A-01');
    expect(task.assignedStaff!.fullName, 'C Natcha');
    expect(task.dueBy, isNull);
  });

  test('ApiException แปลง 409 เป็นข้อความไทยและเก็บ detail จาก FastAPI', () {
    final options = RequestOptions(path: '/tasks/x/accept');
    final error = ApiException.fromDio(DioException(
      requestOptions: options,
      response: Response(
        requestOptions: options,
        statusCode: 409,
        data: {'detail': 'task is IN_PROGRESS, expected PENDING'},
      ),
    ));
    expect(error.statusCode, 409);
    expect(error.message, 'สถานะงานเปลี่ยนไปแล้ว กรุณารีเฟรช');
    expect(error.detail, 'task is IN_PROGRESS, expected PENDING');
  });
}
