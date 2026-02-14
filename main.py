"""
Main entry point for the trading system.
Supports both PAPER and LIVE trading modes with flexible data sources.
"""

import sys
import os
import time
import logging
import threading
import pyotp
from datetime import datetime

# Add src to path if needed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import components
from config import Config
from utils.logger import setup_logging, trade_logger, logger
from utils.time_sync import TimeSync
from utils.notifier import TelegramNotifierTextOnly
from core.feed import UnifiedFeed
from core.state import StrategyState
from paper_broker import PaperBroker
from live_broker import LiveBroker
from strategy.instruments import InstrumentMaster
from strategy.engine import StrategyEngine


def validate_notifier(notifier):
    """
    Validate that notifier implements required protocol methods.
    
    Returns:
        notifier if valid, None if invalid (with logging)
    """
    if notifier is None:
        return None
    
    required_methods = [
        'send_entry',
        'send_exit', 
        'send_trade_log',
        'send_strike_selection',
        'send_phase_change',
        'send_lock_event',
        'send_trade_entry',
        'send_trailing_sl_update',
        'heartbeat'
    ]
    
    missing = []
    for method in required_methods:
        if not hasattr(notifier, method) or not callable(getattr(notifier, method)):
            missing.append(method)
    
    if missing:
        logger.error("=" * 80)
        logger.error(" NOTIFIER VALIDATION FAILED")
        logger.error("=" * 80)
        logger.error(f"Missing methods: {missing}")
        logger.warning(" Notifications will be DISABLED")
        logger.error("=" * 80)
        return None
    
    logger.info("=" * 80)
    logger.info(" NOTIFIER PROTOCOL VALIDATED")
    logger.info("=" * 80)
    logger.info(f"All {len(required_methods)} required methods present")
    logger.info("=" * 80)
    return notifier

# Angel One API (only needed for LIVE modes)
try:
    from SmartApi import SmartConnect
    SMARTAPI_AVAILABLE = True
except ImportError:
    SMARTAPI_AVAILABLE = False
    SmartConnect = None


def create_broker(api_session=None):
    """
    Create appropriate broker based on trading mode.
    
    Args:
        api_session: SmartConnect session (required for LIVE trading)
    
    Returns:
        Broker instance (PaperBroker or LiveBroker)
    """
    logger.info("=" * 80)
    logger.info(f"CREATING BROKER: {Config.TRADING_MODE} MODE")
    logger.info("=" * 80)
    
    # Initialize state
    if Config.RESET_STATE_ON_START and os.path.exists(Config.STATE_FILE):
        logger.warning(" Deleting state (RESET_STATE_ON_START=True)")
        os.remove(Config.STATE_FILE)
    
    # Create notifier first
    notifier = None
    if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
        notifier_raw = TelegramNotifierTextOnly(
            Config.TELEGRAM_BOT_TOKEN,
            Config.TELEGRAM_CHAT_ID,
            interval=Config.TELEGRAM_SNAPSHOT_INTERVAL
        )
        notifier_raw.start()
        
        # CRITICAL: Validate notifier implements required protocol
        notifier = validate_notifier(notifier_raw)
        
        if notifier:
            logger.info(" Telegram notifier started and validated")
        else:
            logger.warning(" Telegram notifier disabled due to validation failure")
    
    # Create state with notifier
    state = StrategyState(Config.STATE_FILE, notifier=notifier)
    
    # Create broker based on mode
    if Config.TRADING_MODE == "LIVE":
        if not SMARTAPI_AVAILABLE:
            logger.critical(" SmartAPI not available for LIVE trading")
            sys.exit(1)
        
        if not api_session:
            logger.critical(" API session required for LIVE trading")
            sys.exit(1)
        
        logger.warning(" LIVE TRADING MODE - REAL MONEY AT RISK!")
        broker = LiveBroker(
            smart_api=api_session,
            state=state,
            trades_csv=Config.get_trades_csv(),
            notifier=notifier,
            lots=Config.LOTS,
            instruments=None  # Will be set after InstrumentMaster is created
        )
    
    else:  # PAPER mode
        logger.info(" PAPER TRADING MODE - Simulated orders only")
        broker = PaperBroker(
            state=state,
            trades_csv=Config.get_trades_csv(),
            notifier=notifier,
            lots=Config.LOTS
        )
    
    return broker, state, notifier


def create_feed(api_session=None):
    """
    Create appropriate data feed based on data mode.
    
    Args:
        api_session: SmartConnect session (required for LIVE data)
    
    Returns:
        UnifiedFeed instance
    """
    logger.info("=" * 80)
    logger.info(f"CREATING DATA FEED: {Config.DATA_MODE} MODE")
    logger.info("=" * 80)
    
    if Config.DATA_MODE == "LIVE":
        if not SMARTAPI_AVAILABLE:
            logger.critical(" SmartAPI not available for LIVE data")
            sys.exit(1)
        
        if not api_session or not hasattr(api_session, 'data'):
            logger.critical(" Valid API session required for LIVE data")
            sys.exit(1)
        
        session_data = api_session.data
        
        feed = UnifiedFeed(
            mode="LIVE",
            auth_token=session_data['jwtToken'],
            api_key=Config.API_KEY,
            client_code=Config.CLIENT_CODE,
            feed_token=session_data['feedToken']
        )
        logger.info(" LIVE data feed initialized")
    
    else:  # REPLAY mode
        feed = UnifiedFeed(
            mode="REPLAY",
            start_date=Config.REPLAY_START_DATE,
            end_date=Config.REPLAY_END_DATE,
            speed=Config.REPLAY_SPEED
        )
        logger.info(" REPLAY data feed initialized")
    
    return feed


def login_to_angel_one():
    """
    Login to Angel One API.
    Required for LIVE data or LIVE trading.
    
    Returns:
        Tuple of (SmartConnect instance, session dict) or (None, None)
    """
    # Only login if we need it
    if Config.DATA_MODE != "LIVE" and Config.TRADING_MODE != "LIVE":
        return None, None
    
    if not SMARTAPI_AVAILABLE:
        logger.critical(" SmartAPI not available")
        sys.exit(1)
    
    logger.info("=" * 80)
    logger.info(" LOGGING IN TO ANGEL ONE")
    logger.info("=" * 80)
    
    try:
        api = SmartConnect(api_key=Config.API_KEY)
        totp = pyotp.TOTP(Config.TOTP_SECRET).now()
        
        logger.info(f"Client Code: {Config.CLIENT_CODE}")
        logger.info(f"TOTP: {totp}")
        
        session = api.generateSession(Config.CLIENT_CODE, Config.PASSWORD, totp)
        
        if not session or not session.get('status'):
            logger.critical(f" Login failed: {session}")
            sys.exit(1)
        
        logger.info(" Login successful")
        logger.info(f"Session: {session.get('data', {}).get('jwtToken', '')[:20]}...")
        
        # Store session in api object for easy access
        api.data = session.get('data', {})
        
        return api, session
    
    except Exception as e:
        logger.critical(f" Login failed: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point"""
    try:
        # UTF-8 Console Fix
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
        
        # Setup
        setup_logging()
        
        print("=" * 80)
        print("TRADING SYSTEM STARTUP")
        print("=" * 80)
        print(f"Data Mode:    {os.getenv('DATA_MODE', 'LIVE')}")
        print(f"Trading Mode: {os.getenv('TRADING_MODE', 'PAPER')}")
        print("=" * 80)
        
        # Validate config
        Config.validate()
        
        # Time sync
        TimeSync.validate_or_abort()
        
        # Login if needed
        api_session, session = login_to_angel_one()
        
        # Create components
        feed = create_feed(api_session)
        broker, state, notifier = create_broker(api_session)
        instruments = InstrumentMaster(Config.CSV_PATH)
        
        # Set instruments in broker for validation
        if hasattr(broker, 'instruments'):
            broker.instruments = instruments
        
        # Attach notifier logging handler
        if notifier:
            try:
                handler = notifier.logging_handler()
                handler.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
                )
                logging.getLogger().addHandler(handler)
                logger.info(" Notifier logging handler attached")
            except Exception as e:
                logger.exception(f"Failed to attach notifier logging handler: {e}")
            
            # Send system status notification
            try:
                login_status = "SUCCESS" if api_session else "NOT_REQUIRED"
                ws_status = "PENDING"  # Will be updated when websocket connects
                notifier.send_system_status(login_status, ws_status)
            except Exception as e:
                logger.exception(f"Failed to send system status: {e}")
        
        time.sleep(2)
        
        # Create strategy engine
        try:
            engine = StrategyEngine(
                feed=feed,
                instruments=instruments,
                broker=broker,
                state=state,
                notifier=notifier
            )
        except TypeError:
            # Fallback for older signature
            engine = StrategyEngine(feed, instruments, broker, state)
            if notifier:
                setattr(engine, 'notifier', notifier)
        
        # Start strategy
        engine.start()
        
        logger.info("=" * 80)
        logger.info(" STRATEGY RUNNING")
        logger.info("=" * 80)
        logger.info(f"Data Source: {Config.DATA_MODE}")
        logger.info(f"Trading Mode: {Config.TRADING_MODE}")
        if Config.TRADING_MODE == "LIVE":
            logger.info("  REAL MONEY AT RISK!")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 80)
        
        # Main loop
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("=" * 80)
        logger.info(" SHUTDOWN INITIATED (Ctrl+C)")
        logger.info("=" * 80)
    
    except Exception as e:
        logger.critical(f" FATAL ERROR: {e}", exc_info=True)
    
    finally:
        # Graceful shutdown
        logger.info("=" * 80)
        logger.info("SHUTDOWN SEQUENCE")
        logger.info("=" * 80)
        
        # Stop strategy engine
        try:
            if 'engine' in locals():
                logger.info("Stopping strategy engine...")
                engine.stop()
                logger.info(" Strategy engine stopped")
        except Exception as e:
            logger.exception(f"Error stopping engine: {e}")
        
        # Close positions if squareoff time
        try:
            if 'broker' in locals() and hasattr(broker, 'close_all'):
                now_time = datetime.now(Config.TZ).time()
                if now_time >= Config.SQUAREOFF_TIME or Config.TRADING_MODE == "LIVE":
                    logger.info("Closing all positions...")
                    
                    # Get market prices
                    market_prices = {}
                    for pos in broker.get_positions():
                        token = pos.get('token')
                        if token:
                            try:
                                ltp = feed.get_ltp(token, check_freshness=False)
                                if ltp is None:
                                    ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                                market_prices[token] = ltp
                            except:
                                market_prices[token] = pos.get('avg_price', 0.0)
                    
                    # Close all
                    broker.close_all(market_prices)
                    logger.info(" All positions closed")
        except Exception as e:
            logger.exception(f"Error closing positions: {e}")
        
        # Stop notifier
        try:
            if 'notifier' in locals() and notifier:
                logger.info("Stopping notifier...")
                notifier.stop()
                logger.info(" Notifier stopped")
        except Exception as e:
            logger.exception(f"Error stopping notifier: {e}")
        
        # Close feed
        try:
            if 'feed' in locals():
                logger.info("Closing data feed...")
                feed.close()
                logger.info(" Feed closed")
        except Exception as e:
            logger.exception(f"Error closing feed: {e}")
        
        logger.info("=" * 80)
        logger.info(" SHUTDOWN COMPLETE")
        logger.info("=" * 80)


if __name__ == "__main__":
    main()
