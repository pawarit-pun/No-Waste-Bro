from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    demo_date: Optional[str] = None
    model_config=SettingsConfigDict(env_file=".env") # selected .env file from root
db_env = Settings()