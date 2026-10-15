import 'json_utils.dart';

/// สถานะของ task (ตรงกับ enum task_status ใน DB)
enum TaskStatus {
  pending('PENDING'),
  inProgress('IN_PROGRESS'),
  completed('COMPLETED'),
  rejected('REJECTED');

  const TaskStatus(this.value);
  final String value;

  static TaskStatus parse(String v) =>
      values.firstWhere((s) => s.value == v, orElse: () => pending);
}

/// ประเภทงาน (ตรงกับ enum action_type ใน DB)
enum ActionType {
  markdown('MARKDOWN'),
  kitchenRepurpose('KITCHEN_REPURPOSE'),
  donate('DONATE'),
  discard('DISCARD');

  const ActionType(this.value);
  final String value;

  static ActionType parse(String v) =>
      values.firstWhere((a) => a.value == v, orElse: () => discard);
}

class TaskProduct {
  const TaskProduct({
    required this.productId,
    required this.name,
    required this.category,
    required this.unitOfMeasure,
    this.imageUrl,
  });

  final String productId;
  final String name;
  final String category;
  final String unitOfMeasure;
  final String? imageUrl;

  factory TaskProduct.fromJson(Map<String, dynamic> json) => TaskProduct(
        productId: json['product_id'] as String,
        name: json['name'] as String,
        category: json['category'] as String,
        unitOfMeasure: json['unit_of_measure'] as String,
        imageUrl: json['image_url'] as String?,
      );
}

class TaskLot {
  const TaskLot({
    required this.lotId,
    required this.currentQuantity,
    required this.expirationDate,
    this.locationAisle,
    this.locationShelf,
  });

  final String lotId;
  final int currentQuantity;
  final DateTime expirationDate;
  final String? locationAisle;
  final String? locationShelf;

  /// เช่น "CHILL-A / A-01"
  String get location =>
      [locationAisle, locationShelf].whereType<String>().join(' / ');

  factory TaskLot.fromJson(Map<String, dynamic> json) => TaskLot(
        lotId: json['lot_id'] as String,
        currentQuantity: toInt(json['current_quantity'])!,
        expirationDate: DateTime.parse(json['expiration_date'] as String),
        locationAisle: json['location_aisle'] as String?,
        locationShelf: json['location_shelf'] as String?,
      );
}

/// ขั้นตอนทำงาน 1 ข้อ (จาก LLM)
class InstructionStep {
  const InstructionStep({required this.title, required this.detail});

  final String title;
  final String detail;

  factory InstructionStep.fromJson(Map<String, dynamic> json) => InstructionStep(
        title: json['title'] as String? ?? '',
        detail: json['detail'] as String? ?? '',
      );
}

class StaffRef {
  const StaffRef({required this.staffId, required this.fullName, this.imageUrl});

  final String staffId;
  final String fullName;
  final String? imageUrl;

  factory StaffRef.fromJson(Map<String, dynamic> json) => StaffRef(
        staffId: json['staff_id'] as String,
        fullName: json['full_name'] as String,
        imageUrl: json['image_url'] as String?,
      );
}

/// Task ในคิวงาน (GET /tasks) และรายละเอียด (GET /tasks/{id})
///
/// field ของหน้ารายละเอียด (assessment, recipe, partner) เก็บแบบ Map ไว้ก่อน
/// แล้วค่อยทำ model เมื่อรู้ว่าดีไซน์ใช้อะไรบ้าง
class Task {
  const Task({
    required this.taskId,
    required this.status,
    required this.actionType,
    required this.actionQuantity,
    required this.priority,
    required this.originalPrice,
    required this.createdAt,
    this.lotId,
    this.productId,
    this.assignedStaffId,
    this.newRecommendedPrice,
    this.discountPct,
    this.expectedProfitImpact,
    this.targetRecipeId,
    this.batchCount,
    this.targetPartnerId,
    this.dueBy,
    this.completedAt,
    this.aiReasoning,
    this.staffInstructions,
    this.instructionSteps = const [],
    this.actualQuantityHandled,
    this.rejectionReason,
    this.product,
    this.lot,
    this.assignedStaff,
    this.assessment,
    this.recipe,
    this.partner,
  });

  final String taskId;
  final TaskStatus status;
  final ActionType actionType;
  final int actionQuantity;
  final int priority;
  final double originalPrice;
  final DateTime createdAt;
  final String? lotId;
  final String? productId;
  final String? assignedStaffId;
  final double? newRecommendedPrice;
  final double? discountPct;
  final double? expectedProfitImpact;
  final String? targetRecipeId;
  final int? batchCount;
  final String? targetPartnerId;
  final DateTime? dueBy;
  final DateTime? completedAt;
  final String? aiReasoning;
  final String? staffInstructions;

  /// ว่าง = ไม่มีขั้นตอน (ใช้ staffInstructions แทน)
  final List<InstructionStep> instructionSteps;
  final int? actualQuantityHandled;
  final String? rejectionReason;
  final TaskProduct? product;
  final TaskLot? lot;
  final StaffRef? assignedStaff;
  final Map<String, dynamic>? assessment;
  final Map<String, dynamic>? recipe;
  final Map<String, dynamic>? partner;

  factory Task.fromJson(Map<String, dynamic> json) {
    Map<String, dynamic>? obj(String key) => json[key] as Map<String, dynamic>?;
    return Task(
      taskId: json['task_id'] as String,
      status: TaskStatus.parse(json['task_status'] as String),
      actionType: ActionType.parse(json['action_type'] as String),
      actionQuantity: toInt(json['action_quantity'])!,
      priority: toInt(json['priority'])!,
      originalPrice: toDouble(json['original_price'])!,
      createdAt: toDateTime(json['created_at'])!,
      lotId: json['lot_id'] as String?,
      productId: json['product_id'] as String?,
      assignedStaffId: json['assigned_staff_id'] as String?,
      newRecommendedPrice: toDouble(json['new_recommended_price']),
      discountPct: toDouble(json['discount_pct']),
      expectedProfitImpact: toDouble(json['expected_profit_impact']),
      targetRecipeId: json['target_recipe_id'] as String?,
      batchCount: toInt(json['batch_count']),
      targetPartnerId: json['target_partner_id'] as String?,
      dueBy: toDateTime(json['due_by']),
      completedAt: toDateTime(json['completed_at']),
      aiReasoning: json['ai_reasoning'] as String?,
      staffInstructions: json['staff_instructions'] as String?,
      instructionSteps: (json['instruction_steps'] as List? ?? const [])
          .map((e) => InstructionStep.fromJson(e as Map<String, dynamic>))
          .toList(),
      actualQuantityHandled: toInt(json['actual_quantity_handled']),
      rejectionReason: json['rejection_reason'] as String?,
      product: obj('product') == null ? null : TaskProduct.fromJson(obj('product')!),
      lot: obj('lot') == null ? null : TaskLot.fromJson(obj('lot')!),
      assignedStaff:
          obj('assigned_staff') == null ? null : StaffRef.fromJson(obj('assigned_staff')!),
      assessment: obj('assessment'),
      recipe: obj('recipe'),
      partner: obj('partner'),
    );
  }
}

/// ผลของ POST /tasks/{id}/complete
class TaskCompleteResult {
  const TaskCompleteResult({required this.task, required this.effects});

  final Task task;

  /// {"lots_updated": [...], "lots_created": [...]}
  final Map<String, dynamic> effects;

  factory TaskCompleteResult.fromJson(Map<String, dynamic> json) => TaskCompleteResult(
        task: Task.fromJson(json['task'] as Map<String, dynamic>),
        effects: json['effects'] as Map<String, dynamic>,
      );
}
