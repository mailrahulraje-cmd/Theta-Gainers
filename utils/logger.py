import logging
import os
import sys
from datetime import datetime
from config import Config

# Ensure log directory exists
os.makedirs(Config.LOG_DIR, exist_ok=True)

def get_log_path(log_type: str) -> str:
    return os.path.join(Config.LOG_DIR, f"{log_type}_{datetime.now(Config.TZ).strftime('%Y%m%d')}.log")

# Setup Basic Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("system"), mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Global logger instance
logger = logging.getLogger("strategy_main")

# Setup Trade Logger
trade_logger = logging.getLogger("TRADES")
trade_logger.setLevel(logging.INFO)
trade_handler = logging.FileHandler(get_log_path("trades"), mode="a", encoding="utf-8")
trade_handler.setFormatter(logging.Formatter("%(asctime)s [TRADE] %(message)s"))
trade_logger.propagate = False
trade_logger.addHandler(trade_handler)

def get_logger(name: str = None) -> logging.Logger:
    """
    Returns a logger instance.
    If name is provided, returns that specific logger.
    Otherwise returns the default strategy logger.
    """
    if name:
        return logging.getLogger(name)
    return logger

def setup_logging():
    """Configures and returns the main logger instance"""
    logger.info("=" * 80)
    logger.info(f"NIFTY THETA STRATEGY v3.0 - {Config.TRADING_MODE} MODE")
    logger.info("=" * 80)
    return logger