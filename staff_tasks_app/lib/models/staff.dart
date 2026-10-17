/// พนักงาน (GET /staff)
class Staff {
  const Staff({
    required this.staffId,
    required this.fullName,
    required this.role,
    required this.responsibleCategories,
    this.imageUrl,
    this.isActive = true,
  });

  final String staffId;
  final String fullName;

  /// MANAGER หรือ STAFF
  final String role;

  /// หมวดสินค้าที่รับผิดชอบ เช่น ["MEAT", "SEAFOOD"]
  final List<String> responsibleCategories;
  final String? imageUrl;
  final bool isActive;

  factory Staff.fromJson(Map<String, dynamic> json) => Staff(
        staffId: json['staff_id'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
        responsibleCategories:
            (json['responsible_categories'] as List? ?? const []).cast<String>(),
        imageUrl: json['image_url'] as String?,
        isActive: json['is_active'] as bool? ?? true,
      );

  Map<String, dynamic> toJson() => {
        'staff_id': staffId,
        'full_name': fullName,
        'role': role,
        'responsible_categories': responsibleCategories,
        'image_url': imageUrl,
        'is_active': isActive,
      };
}
