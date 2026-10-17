/// ค่าตั้งค่าของ app
///
/// เปลี่ยนได้ตอนรันด้วย --dart-define เช่น
/// `flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1` (ใช้ server ในเครื่องแทน AWS)
class AppConfig {
  AppConfig._();

  /// FastAPI server บน AWS Lambda + API Gateway (ค่า ApiBaseUrl จาก sam deploy)
  /// URL จะเปลี่ยนถ้า sam delete แล้ว deploy ใหม่
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1',
  );

  /// Supabase ใช้เฉพาะ Realtime (ฟังว่ามี task ใหม่ / เปลี่ยนสถานะ)
  static const supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: 'https://vvhwqamejfaouvfmkhps.supabase.co',
  );

  /// Publishable key ใส่ใน app ได้: policy ของ DB อนุญาตแค่อ่าน task
  static const supabasePublishableKey = String.fromEnvironment(
    'SUPABASE_PUBLISHABLE_KEY',
    defaultValue: 'sb_publishable_WCY6OrTuQxjfkBRUb_Jqqg_5rHBuAkO',
  );
}
