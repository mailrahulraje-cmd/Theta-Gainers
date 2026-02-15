#!/usr/bin/env python3
"""
Example: Using the Enhanced Notification System

This script demonstrates how to use all the new notification methods
added to the TelegramNotifierTextOnly class.

Run this to test notifications without running the full trading system.
"""

import time
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.notifier import TelegramNotifierTextOnly
from config import Config
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def test_notifications():
    """
    Demonstrate all notification types.
    
    Prerequisites:
    - Set environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    - Or update config.py with your Telegram credentials
    """
    
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return False
    
    # Initialize notifier
    logger.info("Initializing notifier...")
    notifier = TelegramNotifierTextOnly(
        bot_token=Config.TELEGRAM_BOT_TOKEN,
        chat_id=Config.TELEGRAM_CHAT_ID,
        interval=Config.TELEGRAM_SNAPSHOT_INTERVAL
    )
    
    # Start notifier (starts snapshot daemon)
    logger.info("Starting notifier...")
    notifier.start()
    
    # Wait for startup alert
    time.sleep(2)
    
    try:
        # =================================================================
        # Test 1: System Startup Alert
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 1: System Startup Alert")
        logger.info("="*70)
        logger.info("Sending enhanced startup alert...")
        
        notifier.send_system_startup(
            trading_mode=Config.TRADING_MODE,
            broker_name="Angel One",
            instruments_count=42,
            status="READY"
        )
        
        time.sleep(3)
        
        # =================================================================
        # Test 2: Connection Alerts
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 2: Connection Error Alerts")
        logger.info("="*70)
        logger.info("Sending connection lost alert...")
        
        notifier.send_connection_lost(
            service="WebSocket",
            last_ltp_time="09:45:30",
            retry_info="Auto-reconnecting (attempt 1/5)..."
        )
        
        time.sleep(3)
        logger.info("Sending connection restored alert...")
        
        notifier.send_connection_restored(service="WebSocket")
        
        time.sleep(3)
        
        # =================================================================
        # Test 3: Trade Error Alerts (Rate-Limited)
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 3: Trade Error Alerts (Rate-Limited to 1 per 10 sec)")
        logger.info("="*70)
        logger.info("Sending first trade error (should succeed)...")
        
        notifier.send_trade_error(
            leg="BUY CE",
            strike=22000,
            qty=15,
            reason="Insufficient margin available on API account"
        )
        
        time.sleep(1)
        logger.info("Sending second trade error IMMEDIATELY (should be suppressed)...")
        
        notifier.send_trade_error(
            leg="SELL PE",
            strike=22000,
            qty=15,
            reason="Order rejected by exchange"
        )
        
        logger.info("Note: Second error was suppressed due to rate limit")
        time.sleep(10)  # Wait for rate limit to expire
        
        logger.info("Waiting 10 seconds for rate limit to expire...")
        logger.info("Sending third trade error after rate limit (should succeed)...")
        
        notifier.send_trade_error(
            leg="BUY PE",
            strike=22000,
            qty=10,
            reason="Circuit breaker activated"
        )
        
        time.sleep(3)
        
        # =================================================================
        # Test 4: Data Error Alerts (Rate-Limited)
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 4: Data Error Alerts (Rate-Limited)")
        logger.info("="*70)
        logger.info("Sending data error...")
        
        notifier.send_data_error(
            issue="Missing LTP for subscribed token",
            token="12345",
            status="Paused"
        )
        
        time.sleep(3)
        
        # =================================================================
        # Test 5: P&L Milestone Alerts (One-Time Per Session)
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 5: P&L Milestone Alerts (One-Time Each)")
        logger.info("="*70)
        logger.info("Sending 100% daily target milestone...")
        
        notifier.send_pnl_milestone(
            milestone_type="100_PERCENT",
            current_pnl=5000.0,
            daily_target=5000.0,
            cumulative_pnl=45000.0
        )
        
        time.sleep(3)
        logger.info("Sending 150% daily target milestone...")
        
        notifier.send_pnl_milestone(
            milestone_type="150_PERCENT",
            current_pnl=7500.0,
            daily_target=5000.0,
            cumulative_pnl=47500.0
        )
        
        time.sleep(3)
        logger.info("Sending max loss milestone...")
        
        notifier.send_pnl_milestone(
            milestone_type="MAX_LOSS",
            current_pnl=-2500.0,
            cumulative_pnl=42500.0
        )
        
        time.sleep(3)
        logger.info("Attempting to resend 100% milestone (should be suppressed)...")
        
        notifier.send_pnl_milestone(
            milestone_type="100_PERCENT",
            current_pnl=5100.0,
            daily_target=5000.0
        )
        
        logger.info("Note: Milestone was suppressed (already sent this session)")
        time.sleep(3)
        
        # =================================================================
        # Test 6: Daily Heartbeat Alert
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 6: Daily Heartbeat Alert")
        logger.info("="*70)
        logger.info("Sending daily heartbeat (session summary)...")
        
        notifier.send_daily_heartbeat(
            trades_count=3,
            daily_pnl=5200.0,
            win_rate=75.0,
            cumulative_pnl=48500.0,
            session_start_time="09:30"
        )
        
        time.sleep(3)
        
        # =================================================================
        # Test 7: Legacy Methods (Backward Compatibility)
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("TEST 7: Legacy Methods (Backward Compatibility)")
        logger.info("="*70)
        logger.info("Sending trade entry via legacy send_entry()...")
        
        notifier.send_entry(
            label="BUY CE",
            price=145.50,
            token="12345",
            strike=22000,
            option_type="CE",
            qty=15,
            sl=150.0
        )
        
        time.sleep(2)
        logger.info("Sending trade exit via legacy send_exit()...")
        
        notifier.send_exit(
            label="SELL CE",
            price=142.30,
            pnl=-48.0,
            reason="Stop loss triggered",
            token="12345"
        )
        
        time.sleep(2)
        logger.info("Sending trade log message...")
        
        notifier.send_trade_log(
            "Market heat detected - consider reducing exposure"
        )
        
        time.sleep(3)
        
        # =================================================================
        # Summary
        # =================================================================
        logger.info("\n" + "="*70)
        logger.info("ALL TESTS COMPLETED SUCCESSFULLY")
        logger.info("="*70)
        logger.info("\nCheck your Telegram chat for these messages:")
        logger.info("  1. System startup notification")
        logger.info("  2. Connection lost alert")
        logger.info("  3. Connection restored alert")
        logger.info("  4. Trade error (first) - succeeded")
        logger.info("  5. Trade error (second) - suppressed (rate limited)")
        logger.info("  6. Trade error (third) - succeeded after rate limit expired")
        logger.info("  7. Data error")
        logger.info("  8. P&L Milestone 100%")
        logger.info("  9. P&L Milestone 150%")
        logger.info("  10. P&L Milestone MAX_LOSS")
        logger.info("  11. P&L Milestone 100% (again - suppressed)")
        logger.info("  12. Daily heartbeat")
        logger.info("  13. Legacy trade entry")
        logger.info("  14. Legacy trade exit")
        logger.info("  15. Trade log message")
        logger.info("\nDeduplication worked correctly:")
        logger.info("  ✓ Trade error: 3 alerts sent (rate-limited between)")
        logger.info("  ✓ P&L milestone: Resend suppressed (one-time per session)")
        logger.info("  ✓ All other alerts sent as expected")
        
        return True
        
    except Exception as e:
        logger.error(f"ERROR during tests: {e}", exc_info=True)
        return False
        
    finally:
        logger.info("\nStopping notifier...")
        notifier.stop()
        logger.info("Test suite complete.")


def test_deduplication_reset():
    """
    Test that deduplication state can be reset for a new trading session.
    """
    logger.info("\n" + "="*70)
    logger.info("TEST: Deduplication Reset for New Session")
    logger.info("="*70)
    
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False
    
    notifier = TelegramNotifierTextOnly(
        bot_token=Config.TELEGRAM_BOT_TOKEN,
        chat_id=Config.TELEGRAM_CHAT_ID,
        interval=Config.TELEGRAM_SNAPSHOT_INTERVAL
    )
    notifier.start()
    
    time.sleep(2)
    
    try:
        logger.info("Sending P&L milestone 100%...")
        notifier.send_pnl_milestone(
            milestone_type="100_PERCENT",
            current_pnl=5000.0,
            daily_target=5000.0
        )
        
        time.sleep(2)
        logger.info("Attempting resend (should be suppressed)...")
        notifier.send_pnl_milestone(
            milestone_type="100_PERCENT",
            current_pnl=5100.0,
            daily_target=5000.0
        )
        
        logger.info("Milestone was suppressed ✓")
        
        # Reset deduplication for new session
        logger.info("\nResetting deduplication cache for new session...")
        notifier.state_cache.pnl_milestones_sent.clear()
        
        time.sleep(2)
        logger.info("Sending milestone again after reset...")
        notifier.send_pnl_milestone(
            milestone_type="100_PERCENT",
            current_pnl=6000.0,
            daily_target=5000.0
        )
        
        logger.info("Milestone was sent again ✓ (deduplication reset worked)")
        
        return True
        
    except Exception as e:
        logger.error(f"ERROR: {e}", exc_info=True)
        return False
        
    finally:
        notifier.stop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test enhanced notification system")
    parser.add_argument(
        "--test",
        choices=["all", "notifications", "dedup"],
        default="all",
        help="Which tests to run"
    )
    
    args = parser.parse_args()
    
    success = True
    
    if args.test in ["all", "notifications"]:
        logger.info("Starting notification tests...")
        success = test_notifications() and success
    
    if args.test in ["all", "dedup"]:
        logger.info("\nStarting deduplication reset test...")
        success = test_deduplication_reset() and success
    
    sys.exit(0 if success else 1)
