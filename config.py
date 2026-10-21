"""Central configuration. Everything can be overridden with environment variables."""
import os
from datetime import time as dtime

import pytz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("OI_DATA_DIR", os.path.join(BASE_DIR, "data"))
LOG_DIR = os.environ.get("OI_LOG_DIR", os.path.join(BASE_DIR, "logs"))
USER_DATA_FILE = os.environ.get("USER_DATA_FILE", os.path.join(BASE_DIR, "user_data.toml"))

TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
STATUS_FILE = os.path.join(DATA_DIR, "collector_status.json")
LOCK_FILE = os.path.join(DATA_DIR, "collector.lock")

# ---- market / instrument ----
SYMBOL = "NSE:NIFTY50-INDEX"
STRIKE_STEP = 50                                   # NIFTY strike interval
STRIKES_EACH_SIDE = int(os.environ.get("STRIKES_EACH_SIDE", 10))  # window = center ± N strikes
FETCH_STRIKECOUNT = int(os.environ.get("FETCH_STRIKECOUNT", 30))  # strikes Fyers returns each side of live ATM
TZ = pytz.timezone("Asia/Kolkata")
MARKET_START = dtime(9, 15)
MARKET_END = dtime(15, 30)

# ---- UI ----
UI_REFRESH_SECONDS = int(os.environ.get("UI_REFRESH_SECONDS", 30))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
