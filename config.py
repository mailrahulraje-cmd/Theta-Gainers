#!/usr/bin/env python3
import os
import sys
from datetime import time as dt_time
from zoneinfo import ZoneInfo
from datetime import timezone, timedelta
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv not installed in this environment — continue with environment variables
    def load_dotenv():
        return None

# Custom exceptions
class ConfigurationError(Exception):
    """Raised when configuration validation fails"""
    pass

# Angel One API (only needed in LIVE mode)
try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    import pyotp
    SMARTAPI_AVAILABLE = True
except ImportError:
    SMARTAPI_AVAILABLE = False

class Config:
    # ===========================
    # CORE MODE SELECTION
    # ===========================
    DATA_MODE = os.getenv("DATA_MODE", "LIVE")  # "LIVE" or "REPLAY"
    TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")  # "PAPER" or "LIVE"

    # ===========================
    # REPLAY CONFIGURATION
    # ===========================
    REPLAY_START_DATE = os.getenv("REPLAY_START_DATE", "2026-02-04")
    REPLAY_END_DATE = os.getenv("REPLAY_END_DATE", "2026-02-04")
    REPLAY_SPEED = int(os.getenv("REPLAY_SPEED", "30"))
    REPLAY_DATA_DIR = "tick_data"

    # ===========================
    # CREDENTIALS (LIVE MODE ONLY)
    # ===========================
    API_KEY = os.getenv("ANGEL_API_KEY")
    CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
    PASSWORD = os.getenv("ANGEL_PASSWORD")
    TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

    # ===========================
    # FILES & PATHS
    # ===========================
    # Make CSV_PATH absolute relative to this config.py file
    BASE_DIR = Path(__file__).parent
    CSV_PATH = BASE_DIR / "angel_master_instruments.csv"
    STATE_FILE = BASE_DIR / "strategy_state.json"
    LOG_DIR = BASE_DIR / "strategy_logs"
    TICK_RECORDING_DIR = BASE_DIR / "tick_data"
    PAPER_TRADES_CSV = BASE_DIR / "paper_trades.csv"
    LIVE_TRADES_CSV = BASE_DIR / "live_trades.csv"

    # ===========================
    # MARKET CONFIGURATION
    # ===========================
    UNDERLYING_SYMBOL = "NIFTY"
    EXCHANGE = "NFO"
    SPOT_EXCHANGE = "NSE"
    ATM_ROUND = 50
    
    # Strike unit conversion
    # CSV strikes are in paise (e.g., 2450000 for 24500.00)
    # Set to 100 to convert paise to rupees
    STRIKE_UNIT = int(os.getenv("STRIKE_UNIT", "100"))
    
    SELL_CE_OFFSET = 100
    SELL_PE_OFFSET = 100
    OTM_MIN_DISTANCE = 150
    OTM_MAX_DISTANCE = 350

    # ===========================
    # TIME WINDOWS (IST)
    # ===========================
    try:
        TZ = ZoneInfo("Asia/Kolkata")
    except Exception:
        # tzdata not available in this environment; fallback to fixed-offset IST
        TZ = timezone(timedelta(hours=5, minutes=30))
    PHASE0_START = dt_time(9, 15, 50)
    PHASE0_END = dt_time(9, 16, 10)
    PHASE1_START = dt_time(9, 16, 15)
    PHASE1_END = dt_time(9, 16, 45)
    SQUAREOFF_TIME = dt_time(15, 25, 0)

    # ===========================
    # OTM SELECTION (DELTA BASED)
    # ===========================
    TARGET_CE_DELTA = 0.22
    TARGET_PE_DELTA = -0.22
    DELTA_SCAN_RANGE = 8

    OTM_PREMIUM_MIN = 20.0
    OTM_PREMIUM_MAX = 130.0
    OTM_PREMIUM_TARGET = 70.0

    # ===========================
    # ENTRY/EXIT PARAMETERS
    # ===========================
    SELL_ENTRY_DELAY = 1.0
    SELL_DECAY_TRIGGER = 2.0
    BUY_TRIGGER_MULTIPLIER = 1.8
    BUY_TRIGGER_ABSOLUTE = 2.0
    SELL_SL_PERCENT = 0.55
    SELL_TP_PERCENT = 0.98
    BUY_SL_POINTS = 50.0
    BUY_TP_POINTS = 80.0

    # ===========================
    # POSITION SIZING
    # ===========================
    LOTS = int(os.getenv("LOTS", "1"))

    # ===========================
    # ORDER EXECUTION
    # ===========================
    ORDER_TYPE = os.getenv("ORDER_TYPE", "MARKET")
    LIMIT_PRICE_OFFSET_PERCENT = float(os.getenv("LIMIT_PRICE_OFFSET_PERCENT", "0.5"))
    ORDER_VARIETY = os.getenv("ORDER_VARIETY", "NORMAL")
    PRODUCT_TYPE = os.getenv("PRODUCT_TYPE", "INTRADAY")
    ORDER_MAX_RETRIES = int(os.getenv("ORDER_MAX_RETRIES", "3"))
    ORDER_RETRY_DELAY = float(os.getenv("ORDER_RETRY_DELAY", "1.0"))
    # API call retry policy (for network hardening)
    API_CALL_MAX_RETRIES = int(os.getenv("API_CALL_MAX_RETRIES", "3"))
    API_CALL_RETRY_DELAY = float(os.getenv("API_CALL_RETRY_DELAY", "1.0"))

    # ===========================
    # RISK MANAGEMENT
    # ===========================
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "10000"))
    MAX_TRADE_LOSS = float(os.getenv("MAX_TRADE_LOSS", "2000"))
    ENABLE_CIRCUIT_BREAKER = os.getenv("ENABLE_CIRCUIT_BREAKER", "true").lower() == "true"
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
    MAX_POSITION_PERCENT = float(os.getenv("MAX_POSITION_PERCENT", "80"))
    
    # ===========================
    # VALIDATION SETTINGS
    # ===========================
    REQUIRE_LIVE_CONFIRMATION = os.getenv("REQUIRE_LIVE_CONFIRMATION", "true").lower() == "true"
    MIN_ORDER_INTERVAL = float(os.getenv("MIN_ORDER_INTERVAL", "1.0"))
    ENABLE_ORDER_VALIDATION = os.getenv("ENABLE_ORDER_VALIDATION", "true").lower() == "true"
    ENABLE_POSITION_RECONCILIATION = os.getenv("ENABLE_POSITION_RECONCILIATION", "true").lower() == "true"
    POSITION_RECONCILIATION_INTERVAL = int(os.getenv("POSITION_RECONCILIATION_INTERVAL", "60"))
    PRICE_TOLERANCE_PERCENT = float(os.getenv("PRICE_TOLERANCE_PERCENT", "5.0"))
    MAX_ORDER_QUANTITY = int(os.getenv("MAX_ORDER_QUANTITY", "1000"))

    # ===========================
    # SYSTEM PARAMETERS
    # ===========================
    MAX_TIME_DRIFT_SECONDS = 3.0
    NTP_SERVER = "time.google.com"
    HEARTBEAT_INTERVAL = 5.0
    SUBSCRIPTION_DELAY = 0.2
    TICK_FRESHNESS_SECONDS = 5.0
    RESET_STATE_ON_START = os.getenv("RESET_STATE_ON_START", "false").lower() == "true"
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    # Order rate limiting
    MAX_ORDERS_PER_MINUTE = int(os.getenv("MAX_ORDERS_PER_MINUTE", "20"))
    
    # ===========================
    # PHASE EXECUTION PARAMETERS
    # ===========================
    # Phase 1 retry and data wait configuration
    PHASE1_MAX_ATTEMPTS = int(os.getenv("PHASE1_MAX_ATTEMPTS", "3"))  # Max attempts for hedge selection
    PHASE1_DATA_WAIT_SECONDS = float(os.getenv("PHASE1_DATA_WAIT_SECONDS", "10.0"))  # Max wait for option data
    PHASE1_DATA_CHECK_INTERVAL = float(os.getenv("PHASE1_DATA_CHECK_INTERVAL", "0.5"))  # Check interval
    PHASE1_RETRY_DELAY = float(os.getenv("PHASE1_RETRY_DELAY", "2.0"))  # Delay between retry attempts
    FIRST_TICK_GRACE_SECONDS = float(os.getenv("FIRST_TICK_GRACE_SECONDS", "5.0"))  # Grace for first tick

    # ===========================
    # FEED HEALTH MONITORING
    # ===========================
    FEED_HEALTH_CHECK_INTERVAL = float(os.getenv("FEED_HEALTH_CHECK_INTERVAL", "2.0"))  # seconds between health checks
    FEED_DEGRADED_THRESHOLD = float(os.getenv("FEED_DEGRADED_THRESHOLD", "10.0"))  # seconds without tick = degraded
    FEED_DEAD_THRESHOLD = float(os.getenv("FEED_DEAD_THRESHOLD", "30.0"))  # seconds without tick = dead
    FEED_MIN_TOKENS_FOR_HEALTH = int(os.getenv("FEED_MIN_TOKENS_FOR_HEALTH", "1"))  # min subscribed tokens to check
    
    # ===========================
    # OPERATIONAL TIMEOUTS
    # ===========================
    MAX_ORDER_PLACEMENT_TIME = float(os.getenv("MAX_ORDER_PLACEMENT_TIME", "5.0"))  # max seconds from signal to order placed
    MAX_ORDER_CONFIRMATION_TIME = float(os.getenv("MAX_ORDER_CONFIRMATION_TIME", "10.0"))  # max seconds for order confirmation
    MAX_EXIT_EXECUTION_TIME = float(os.getenv("MAX_EXIT_EXECUTION_TIME", "8.0"))  # max seconds for exit order execution
    ENABLE_TIMEOUT_PROTECTION = os.getenv("ENABLE_TIMEOUT_PROTECTION", "true").lower() == "true"
    
    # ===========================
    # KILL SWITCH
    # ===========================
    KILL_SWITCH_ENABLED = os.getenv("KILL_SWITCH_ENABLED", "false").lower() == "true"  # Manual kill switch
    NO_NEW_TRADES = os.getenv("NO_NEW_TRADES", "false").lower() == "true"  # Block new trade entries
    EMERGENCY_EXIT_ALL = os.getenv("EMERGENCY_EXIT_ALL", "false").lower() == "true"  # Exit all positions immediately
    # File-based emergency stop flag (presence of file triggers emergency flatten)
    EMERGENCY_STOP_FILE = BASE_DIR / os.getenv("EMERGENCY_STOP_FILE", "EMERGENCY_STOP.flag")

    # ===========================
    # TRAILING STOP-LOSS (SELL LEGS ONLY)
    # ===========================
    # Time window for passive price observation (12:00 to 14:00 IST)
    TRAILING_OBSERVATION_START = dt_time(12, 0, 0)
    TRAILING_OBSERVATION_END = dt_time(14, 0, 0)
    
    # Trailing activation time (14:15 IST onwards)
    TRAILING_ACTIVATION_TIME = dt_time(14, 15, 0)
    
    # Trailing buffer as a percentage (e.g., 0.05 = 5%)
    # This is the buffer applied to the adverse price tracked during observation window
    TRAILING_BUFFER_PERCENT = float(os.getenv("TRAILING_BUFFER_PERCENT", "0.05"))

    # ------------------------------------------------------------------
    # Backwards-compatible fraction aliases
    # ------------------------------------------------------------------
    # Many parts of the codebase treat the above PERCENT values as fractions
    # (e.g., using `entry * (1 + Config.SELL_SL_PERCENT)`). To avoid breaking
    # existing logic while clarifying intent, provide explicit _FRACTION aliases
    # and keep the original names for backward compatibility.
    SELL_SL_FRACTION = SELL_SL_PERCENT
    SELL_TP_FRACTION = SELL_TP_PERCENT
    TRAILING_BUFFER_FRACTION = TRAILING_BUFFER_PERCENT
    
    # ===========================
    # MAIN LOOP CONTROL & API RATE LIMITING
    # ===========================
    # Fixed minimum interval per main loop iteration (seconds)
    # Prevents API spamming and high CPU usage
    MAIN_LOOP_INTERVAL_SECONDS = float(os.getenv("MAIN_LOOP_INTERVAL_SECONDS", "0.5"))
    
    # API call rate limit (calls per second)
    # Used for order placement, data fetch, and status checks
    API_RATE_LIMIT_PER_SECOND = float(os.getenv("API_RATE_LIMIT_PER_SECOND", "2.0"))
    
    # ===========================
    # HARD EXIT (MARKET CLOSE ENFORCEMENT)
    # ===========================
    # Time after which all positions MUST be closed (HH:MM format, IST)
    # Default: 15:15 (before 15:30 market close)
    HARD_EXIT_TIME = os.getenv("HARD_EXIT_TIME", "15:15")
    
    # Disable new entries after hard exit (prevents late entries)
    DISABLE_ENTRIES_AFTER_HARD_EXIT = os.getenv("DISABLE_ENTRIES_AFTER_HARD_EXIT", "true").lower() == "true"
    
    # In PAPER mode, ignore market hours for HARD_EXIT (allows 24/7 testing)
    # In LIVE mode, HARD_EXIT is always enforced at HARD_EXIT_TIME
    IGNORE_MARKET_HOURS_IN_PAPER = os.getenv("IGNORE_MARKET_HOURS_IN_PAPER", "true").lower() == "true"
    
    # ===========================
    # DELTA LOOP STABILIZATION
    # ===========================
    # Maximum time to wait for delta finding loop (seconds)
    # If delta loop takes longer, it will timeout and continue
    DELTA_LOOP_TIMEOUT = float(os.getenv("DELTA_LOOP_TIMEOUT", "5.0"))
    
    # Maximum retry attempts for delta finding loop
    # If loop fails to converge, it will retry up to this many times
    DELTA_LOOP_MAX_RETRIES = int(os.getenv("DELTA_LOOP_MAX_RETRIES", "3"))
    
    # ===========================
    # TELEGRAM NOTIFICATIONS
    # ===========================
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    # ⭐ FIXED 30-SECOND SNAPSHOT INTERVAL (Requirement: fixed interval independent of price/P&L)
    # Override: Set env var TELEGRAM_SNAPSHOT_INTERVAL_OVERRIDE to change
    _interval_override = os.getenv("TELEGRAM_SNAPSHOT_INTERVAL_OVERRIDE")
    TELEGRAM_SNAPSHOT_INTERVAL = int(_interval_override) if _interval_override else 30
    TELEGRAM_SNAPSHOT_LINES = int(os.getenv("TELEGRAM_SNAPSHOT_LINES", "60"))
    
    # NOTIFICATION ALERT FLAGS (Enable/Disable specific alert types)
    NOTIFY_STARTUP = os.getenv("NOTIFY_STARTUP", "true").lower() == "true"
    NOTIFY_ERRORS = os.getenv("NOTIFY_ERRORS", "true").lower() == "true"
    NOTIFY_ENTRIES = os.getenv("NOTIFY_ENTRIES", "true").lower() == "true"
    NOTIFY_EXITS = os.getenv("NOTIFY_EXITS", "true").lower() == "true"
    NOTIFY_SL_CHANGES = os.getenv("NOTIFY_SL_CHANGES", "true").lower() == "true"
    NOTIFY_PNL_MILESTONES = os.getenv("NOTIFY_PNL_MILESTONES", "true").lower() == "true"
    NOTIFY_CONNECTION_EVENTS = os.getenv("NOTIFY_CONNECTION_EVENTS", "true").lower() == "true"
    
    # P&L MILESTONE THRESHOLDS
    # Set to 0 to disable a milestone
    PNL_MILESTONE_100_PERCENT = os.getenv("PNL_MILESTONE_100_PERCENT", "true").lower() == "true"
    PNL_MILESTONE_150_PERCENT = os.getenv("PNL_MILESTONE_150_PERCENT", "true").lower() == "true"
    PNL_MAX_DAILY_LOSS_PERCENT = float(os.getenv("PNL_MAX_DAILY_LOSS_PERCENT", "50.0"))  # 50% of capital
    
    # PERIODIC SNAPSHOT SETTINGS
    # Snapshot frequency (in seconds) - only during IN_TRADE phase
    SNAPSHOT_ONLY_IN_TRADE = os.getenv("SNAPSHOT_ONLY_IN_TRADE", "true").lower() == "true"
    # Skip snapshot if P&L change since last snapshot is less than threshold
    SNAPSHOT_PNL_THRESHOLD = float(os.getenv("SNAPSHOT_PNL_THRESHOLD", "10.0"))  # rupees
    
    # DAILY HEARTBEAT SETTINGS
    HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
    # Time to send daily heartbeat (IST, HH:MM format)
    HEARTBEAT_TIME = os.getenv("HEARTBEAT_TIME", "15:45")
    
    # ERROR DEDUPLICATION
    # Rate limit errors: max 1 alert per N seconds per error type
    ERROR_RATE_LIMIT_SECONDS = int(os.getenv("ERROR_RATE_LIMIT_SECONDS", "10"))

    @classmethod
    def validate(cls):
        errors = []
        
        # Parse HARD_EXIT_TIME
        try:
            parts = cls.HARD_EXIT_TIME.split(":")
            if len(parts) != 2:
                raise ValueError("HARD_EXIT_TIME must be HH:MM format")
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid hour/minute values")
            cls._hard_exit_time = dt_time(hour, minute)
        except Exception as e:
            errors.append(f"Invalid HARD_EXIT_TIME '{cls.HARD_EXIT_TIME}': {e}")

        # Validate modes
        if cls.DATA_MODE not in ["LIVE", "REPLAY"]:
            errors.append(f"Invalid DATA_MODE: {cls.DATA_MODE}")
        if cls.TRADING_MODE not in ["PAPER", "LIVE"]:
            errors.append(f"Invalid TRADING_MODE: {cls.TRADING_MODE}")

        # Validate dependencies
        if cls.DATA_MODE == "LIVE" and not SMARTAPI_AVAILABLE:
            errors.append("DATA_MODE=LIVE requires smartapi-python package")
        if cls.TRADING_MODE == "LIVE" and not SMARTAPI_AVAILABLE:
            errors.append("TRADING_MODE=LIVE requires smartapi-python package")
        if cls.DATA_MODE == "REPLAY":
            replay_dir = cls.REPLAY_DATA_DIR

            # Resolve relative paths from project root (config.py location)
            if not os.path.isabs(replay_dir):
                base_dir = os.path.dirname(os.path.abspath(__file__))
                replay_dir = os.path.join(base_dir, replay_dir)

            if not os.path.isdir(replay_dir):
                errors.append(f"REPLAY_DATA_DIR not found: {replay_dir}")
            else:
                # Normalize path so rest of system uses resolved directory
                cls.REPLAY_DATA_DIR = replay_dir


        # Validate credentials for LIVE
        if cls.TRADING_MODE == "LIVE":
            for cred_name in ["API_KEY", "CLIENT_CODE", "PASSWORD", "TOTP_SECRET"]:
                if not getattr(cls, cred_name):
                    errors.append(f"{cred_name} required for LIVE trading")

        # Validate CSV
        if not cls.CSV_PATH.exists():
            errors.append(f"Instrument CSV not found: {cls.CSV_PATH}")

        # Report errors
        if errors:
            error_msg = "\n".join(f"   {e}" for e in errors)
            full_msg = (
                "="*80 + "\n"
                " CONFIGURATION VALIDATION FAILED\n"
                "="*80 + "\n"
                f"{error_msg}\n"
                "="*80
            )
            # Raise exception instead of sys.exit - let main() handle
            raise ConfigurationError(full_msg)

        print("="*80)
        print(" CONFIGURATION VALIDATED")
        print("="*80)
        print(f"   DATA MODE:    {cls.DATA_MODE}")
        print(f"   TRADING MODE: {cls.TRADING_MODE}")
        print("="*80)

    @classmethod
    def get_trades_csv(cls):
        return cls.LIVE_TRADES_CSV if cls.TRADING_MODE == "LIVE" else cls.PAPER_TRADES_CSV
    
    @classmethod
    def get_hard_exit_time(cls) -> dt_time:
        """Get parsed HARD_EXIT_TIME as datetime.time object"""
        if not hasattr(cls, '_hard_exit_time'):
            parts = cls.HARD_EXIT_TIME.split(":")
            hour, minute = int(parts[0]), int(parts[1])
            cls._hard_exit_time = dt_time(hour, minute)
        return cls._hard_exit_time

# Exchange type mapping
EXCHANGE_TYPE_MAP = {"NSE": 1, "NFO": 2, "BSE": 3, "MCX": 5}
