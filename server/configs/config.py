from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    demo_date: Optional[str] = None
    cors_origins: str = "*"  # comma-separated เช่น http://localhost:3000,http://localhost:5173
    optimizer_path: Optional[str] = None
    pipeline_function_name: Optional[str] = None  # Lambda ของ AI pipeline worker (ว่าง = POST /ai/pipeline-runs ตอบ 503)
    model_config=SettingsConfigDict(env_file=".env") # selected .env file from root
db_env = Settings()