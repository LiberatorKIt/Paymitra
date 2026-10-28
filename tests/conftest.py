import os
import sys
from pathlib import Path

# Tests always run offline against a throwaway database.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{ROOT / 'test_paymitra.db'}"
os.environ["LLM_MODE"] = "offline"
os.environ["APP_PASSWORD"] = ""
os.environ["SEED_IF_EMPTY"] = "true"
for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "OWNER_WHATSAPP"):
    os.environ[key] = ""
