"""
Telegram gateway

Single gateway function for all Telegram outgoing messages.
All code should call `send_telegram_message(message: str)` so we have
one place to control retries, rate-limiting and logging.
"""
import logging
import requests
from config import Config

logger = logging.getLogger(__name__)

# Shared requests session for connection pooling
_session = requests.Session()

def send_telegram_message(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message to Telegram using Config credentials.

    Returns True on HTTP 200, False otherwise. Never raises.
    """
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.debug("Telegram credentials missing - skipping send")
        return False

    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = _session.post(
            url,
            data={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode},
            timeout=12
        )
        ok = resp.status_code == 200
        if not ok:
            logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
        return ok
    except Exception as e:
        logger.error(f"Telegram gateway exception: {e}")
        return False
