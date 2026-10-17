/// ตัวช่วยอ่าน JSON จาก API (ตัวเลขจาก Postgres อาจมาเป็น int หรือ double)
double? toDouble(Object? v) => v == null ? null : (v as num).toDouble();

int? toInt(Object? v) => v == null ? null : (v as num).toInt();

DateTime? toDateTime(Object? v) =>
    v == null ? null : DateTime.parse(v as String).toLocal();
