/// ค่าตั้งค่าของ app
///
/// เปลี่ยนได้ตอนรันด้วย --dart-define เช่น
/// `flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1`
class AppConfig {
  AppConfig._();

  /// FastAPI server (iOS Simulator เรียก localhost ของเครื่อง Mac ได้ตรงๆ)
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api/v1',
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
