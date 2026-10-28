"""All settings come from environment variables (or a local .env file).

Nothing secret is hard-coded. Every value has a safe default so the app
runs on a laptop with zero setup (offline mode, SQLite, no login).
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def env(key: str, default: str = "") -> str:
    """Read a setting; an unset OR empty variable falls back to the default."""
    value = (os.getenv(key) or "").strip()
    return value or default


# --- LLM providers -----------------------------------------------------------
GEMINI_API_KEY = env("GEMINI_API_KEY")
NVIDIA_API_KEY = env("NVIDIA_API_KEY")
NVIDIA_BASE_URL = env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Model IDs (checked 28 Oct 2026). Change here, not in code.
MODEL_REASON = env("MODEL_REASON", "gemini-3.8-flash")          # decide + draft
MODEL_CHEAP = env("MODEL_CHEAP", "gemini-3.5-flash-lite")        # briefs, one-liners
MODEL_CLASSIFY = env("MODEL_CLASSIFY", "nvidia/nemotron-3.5-lightning-30b-a3b")  # reply intent
MODEL_VISION = env("MODEL_VISION", "nvidia/nemotron-3.5-super-vl-120b-a12b")     # POD / screenshots

# auto    = use whichever API keys are present, fall back to offline rules
# offline = never call an LLM (safe for demos without internet / keys)
LLM_MODE = env("LLM_MODE", "auto").lower()
LLM_TIMEOUT_SECONDS = float(env("LLM_TIMEOUT_SECONDS", "25"))

# --- Database ------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL", "sqlite:///./paymitra.db")
# Hosts hand out "postgres://..." or "postgresql://..."; point both at the installed driver (psycopg2).
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len(_prefix):]
SEED_IF_EMPTY = env("SEED_IF_EMPTY", "true").lower() == "true"

# --- Website access --------------------------------------------------------------
APP_PASSWORD = env("APP_PASSWORD")            # empty = no login screen
SECRET_KEY = env("SECRET_KEY", "change-me-in-production")
CYCLE_TOKEN = env("CYCLE_TOKEN")              # lets a cron job trigger the daily cycle
# On Render the site address is filled in automatically (RENDER_EXTERNAL_URL).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL") or env("RENDER_EXTERNAL_URL", "http://localhost:8000")

# --- WhatsApp (Twilio) -------------------------------------------------------------
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = env("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
OWNER_WHATSAPP = env("OWNER_WHATSAPP")        # e.g. whatsapp:+9198XXXXXXXX
VALIDATE_TWILIO_SIGNATURE = env("VALIDATE_TWILIO_SIGNATURE", "false").lower() == "true"

# --- Finance assumptions (illustrative; confirm with a CA) ---------------------------
# RBI bank rate = MSF rate = repo + 0.25%. Repo was raised to 5.50% on 7 Oct 2026.
BANK_RATE_PCT = float(env("BANK_RATE_PCT", "5.75"))
OD_RATE_PCT = float(env("OD_RATE_PCT", "14.0"))          # owner's cash-credit line
TREDS_RATE_PCT = float(env("TREDS_RATE_PCT", "7.5"))     # priced on the buyer's credit
TREDS_FEE_PCT = float(env("TREDS_FEE_PCT", "0.10"))      # platform + bank charges, on amount
MISSED_PAYROLL_COST = float(env("MISSED_PAYROLL_COST", "50000"))  # penalty of a late payroll
STATUTORY_DAYS = 45                                     # MSMED Act Sec 15 cap


def llm_online() -> bool:
    return LLM_MODE != "offline" and bool(GEMINI_API_KEY or NVIDIA_API_KEY)


def twilio_ready() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and OWNER_WHATSAPP)


# --- Business clock -----------------------------------------------------------------
# Ages, due dates and "today" follow the MSME's time zone, not the server's (UTC on most hosts).
TIMEZONE = ZoneInfo(env("TIMEZONE", "Asia/Kolkata"))


def now() -> datetime:
    """Naive local time in the business time zone (stored as-is in the database)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None)


def today() -> date:
    return now().date()
