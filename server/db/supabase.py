from supabase import create_client, Client
from configs.config import db_env

supabase: Client = create_client(supabase_url=db_env.supabase_url, supabase_key=db_env.supabase_service_role_key)