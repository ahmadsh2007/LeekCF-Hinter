import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from supabase import create_client, Client

# ENV_FILE points a run at another project (e.g. staging) without touching config/.env.
envPath = Path(os.environ.get("ENV_FILE") or Path('.') / 'config' / '.env')
load_dotenv(dotenv_path=envPath)

SUPABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_DATABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(f"You are missing SUPABASE_DATABASE_URL or SUPABASE_DATABASE_SECRET_KEY (looked in {envPath}).")

print(f"Supabase target: {urlparse(SUPABASE_URL).hostname}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)