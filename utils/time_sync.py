import ntplib
import sys
from config import Config
from .logger import logger

class TimeSync:
    @staticmethod
    def validate_or_abort():
        if Config.DATA_MODE == "REPLAY":
            logger.info(" Skipping NTP sync (REPLAY mode)")
            return
        try:
            ntp_client = ntplib.NTPClient()
            response = ntp_client.request(Config.NTP_SERVER, version=3, timeout=5)
            drift = abs(response.offset)
            logger.info(f" Time drift: {drift:.3f}s")
            if drift > Config.MAX_TIME_DRIFT_SECONDS:
                logger.critical(f" TIME DRIFT TOO HIGH: {drift:.3f}s")
                sys.exit(1)
            logger.info(f" Time sync OK")
        except Exception as e:
            logger.critical(f" Time sync failed: {e}")
            sys.exit(1)