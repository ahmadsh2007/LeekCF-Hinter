import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

envPath = Path('.') / 'config' / '.env'
load_dotenv(dotenv_path=envPath)

SUPABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_DATABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("You are missing SUPABASE_URL or SUPABASE_KEY in environment.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)