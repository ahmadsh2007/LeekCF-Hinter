import os
from pathlib import Path
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions
from src.utils.resilientTransport import RetryingTransport

# ENV_FILE points a run at another project (e.g. staging) without touching config/.env.
envPath = Path(os.environ.get("ENV_FILE") or Path('.') / 'config' / '.env')
load_dotenv(dotenv_path=envPath)

SUPABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_DATABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(f"You are missing SUPABASE_DATABASE_URL or SUPABASE_DATABASE_SECRET_KEY (looked in {envPath}).")

print(f"Supabase target: {urlparse(SUPABASE_URL).hostname}")

# A failed connection attempt is retried a few times by the transport itself, and RetryingTransport sends a request
# again after a gateway error (502/503/504) or a dropped connection, so a short outage of the database never kills a
# long run. The workers add their own "try again later" handling on top (src/utils/retry.py).
httpClient = httpx.Client(transport=RetryingTransport(httpx.HTTPTransport(retries=3)), timeout=60.0)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY, options=SyncClientOptions(httpx_client=httpClient))