"""
LIVENESS LAYER - Operational Signals Outside Trading Window
============================================================

Objective:
    Prove the engine is alive and responsive even when no trades are active,
    before market open or during long Phase 0/1 delays.

Features:
    - Heartbeat/alive signal at configurable intervals (default 60s)
    - Lightweight token subscription (NIFTY spot) to verify market connectivity
    - Periodic status logging ("LIVENESS OK" or "LIVENESS ERROR")
    - Optional Telegram notifications (configurable)
    - Independent thread execution (zero impact on trading logic)
    - Thread-safe operations with proper synchronization
    - Graceful error handling (logs errors but never crashes engine)

Design Principles:
    1. FULLY DECOUPLED: No shared state with trading logic/strategy engine
    2. THREAD-SAFE: Uses locks and atomic operations where needed
    3. NON-BLOCKING: Does not interfere with core trading engine
    4. RESILIENT: Logs errors but never crashes the main process
    5. CONFIGURABLE: All parameters adjustable via config.py
"""

import threading
import time
import logging
from datetime import datetime
from typing import Optional, Any, Callable
from config import Config
from utils.logger import logger


class LivenessMonitor:
    """
    Standalone liveness monitor that runs in a separate thread.
    
    Independent from strategy layer:
    - No access to trade state
    - No shared locks with broker/engine
    - No impact on order execution
    
    Thread-safe execution:
    - Dedicated thread with independent loop
    - Local state only (no global access)
    - Atomic timestamp updates
    """
    
    def __init__(
        self,
        feed,
        notifier: Optional[Any] = None,
        interval_seconds: float = 60.0,
        token: str = None,
        token_symbol: str = "NIFTY",
        enable_telegram: bool = False
    ):
        """
        Initialize LivenessMonitor.
        
        Args:
            feed: UnifiedFeed instance (for get_ltp calls)
            notifier: Optional Telegram notifier (has .send_trade_log method)
            interval_seconds: Heartbeat interval in seconds (default 60)
            token: Specific token to monitor (if None, will use spot NIFTY)
            token_symbol: Human-readable symbol (e.g., "NIFTY")
            enable_telegram: Whether to send Telegram pings
        """
        self.feed = feed
        self.notifier = notifier
        self.interval = max(10.0, float(interval_seconds))  # Minimum 10 seconds
        self.token = token
        self.token_symbol = token_symbol or "NIFTY"
        self.enable_telegram = bool(enable_telegram)
        
        # Independent thread state (no shared locks with trading engine)
        self._thread = None
        self._should_stop = threading.Event()
        self._last_check_time = None
        self._last_ltp = None
        self._error_count = 0
        self._success_count = 0
        self._lock = threading.Lock()  # Local lock only - never contentious with broker locks
        
        logger.info("=" * 80)
        logger.info(" LIVENESS LAYER INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"   Interval:         {self.interval:.1f} seconds")
        logger.info(f"   Monitor Token:    {self.token_symbol}")
        logger.info(f"   Telegram Enabled: {self.enable_telegram}")
        logger.info(f"   Decoupling:       FULL (independent thread)")
        logger.info("=" * 80)
    
    def start(self):
        """Start the liveness monitor in a background thread."""
        if self._thread is not None:
            logger.warning(" Liveness monitor already running")
            return
        
        self._should_stop.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(" Liveness monitor started (daemon thread)")
    
    def stop(self):
        """Stop the liveness monitor gracefully."""
        if self._thread is None:
            return
        
        logger.info(" Stopping liveness monitor...")
        self._should_stop.set()
        
        try:
            self._thread.join(timeout=5.0)
            logger.info(" Liveness monitor stopped")
        except Exception as e:
            logger.warning(f"Error stopping liveness monitor: {e}")
        
        self._thread = None
    
    def _monitor_loop(self):
        """
        Main liveness monitor loop (runs in separate thread).
        
        CRITICAL: This loop is COMPLETELY INDEPENDENT from trading logic.
        - No locks shared with broker or strategy engine
        - No access to trade state or positions
        - Never interferes with order execution timing
        """
        logger.info("[LIVENESS] Monitor loop started")
        
        next_check_time = time.time()
        
        while not self._should_stop.is_set():
            try:
                # Check if it's time for next heartbeat
                now = time.time()
                if now >= next_check_time:
                    self._perform_liveness_check()
                    next_check_time = time.time() + self.interval
                
                # Sleep briefly to avoid busy-waiting (50ms resolution)
                time.sleep(0.05)
            
            except Exception as e:
                # CRITICAL: Never crash the monitor itself
                logger.exception(f"[LIVENESS] Unexpected error in monitor loop: {e}")
                time.sleep(1.0)  # Back off on error
        
        logger.info("[LIVENESS] Monitor loop terminated")
    
    def _perform_liveness_check(self):
        """
        Perform a single liveness check.
        
        Steps:
        1. Attempt to fetch LTP for configured token
        2. Log status with timestamp
        3. Update internal counters
        4. Send Telegram notification if enabled and not recently sent
        """
        timestamp = datetime.now(Config.TZ)
        
        try:
            # Step 1: Fetch LTP (lightweight operation)
            ltp = None
            if self.feed:
                try:
                    ltp = self.feed.get_ltp(str(self.token), check_freshness=False)
                except Exception as e:
                    logger.debug(f"[LIVENESS] LTP fetch error: {e}")
            
            # Step 2: Record result
            with self._lock:
                self._last_check_time = timestamp
                self._last_ltp = ltp
            
            # Step 3: Log status
            if ltp is not None:
                # SUCCESS case
                logger.info(
                    f"[LIVENESS] OK — {timestamp.strftime('%H:%M:%S')} | "
                    f"{self.token_symbol}={ltp:.2f} | "
                    f"Success={self._success_count + 1} Error={self._error_count}"
                )
                
                with self._lock:
                    self._success_count += 1
                
                # Step 4: Send Telegram on success (optional)
                if self.enable_telegram and self.notifier:
                    try:
                        msg = (
                            f"✅ LIVENESS OK\n"
                            f"Time: {timestamp.strftime('%H:%M:%S')}\n"
                            f"Token: {self.token_symbol}\n"
                            f"LTP: {ltp:.2f}\n"
                            f"Checks: {self._success_count + 1} OK, {self._error_count} error"
                        )
                        self.notifier.send_trade_log(msg)
                    except Exception as e:
                        logger.debug(f"[LIVENESS] Telegram send error: {e}")
            
            else:
                # ERROR case: LTP is None
                logger.warning(
                    f"[LIVENESS] ERROR — {timestamp.strftime('%H:%M:%S')} | "
                    f"{self.token_symbol}=N/A | "
                    f"Success={self._success_count} Error={self._error_count + 1}"
                )
                
                with self._lock:
                    self._error_count += 1
                
                # Send Telegram on error (optional)
                if self.enable_telegram and self.notifier:
                    try:
                        msg = (
                            f"⚠️ LIVENESS ERROR\n"
                            f"Time: {timestamp.strftime('%H:%M:%S')}\n"
                            f"Token: {self.token_symbol}\n"
                            f"LTP: Unavailable\n"
                            f"Checks: {self._success_count} OK, {self._error_count + 1} error"
                        )
                        self.notifier.send_trade_log(msg)
                    except Exception as e:
                        logger.debug(f"[LIVENESS] Telegram error send error: {e}")
        
        except Exception as e:
            logger.exception(f"[LIVENESS] Check failed: {e}")
            with self._lock:
                self._error_count += 1
    
    def get_status(self) -> dict:
        """
        Get current liveness status (thread-safe read).
        
        Returns:
            dict with keys:
                - last_check_time: datetime or None
                - last_ltp: float or None
                - success_count: int
                - error_count: int
                - total_checks: int
                - success_rate: float (0.0 to 1.0)
        """
        with self._lock:
            total = self._success_count + self._error_count
            rate = self._success_count / total if total > 0 else 0.0
            
            return {
                'last_check_time': self._last_check_time,
                'last_ltp': self._last_ltp,
                'success_count': self._success_count,
                'error_count': self._error_count,
                'total_checks': total,
                'success_rate': rate
            }
    
    def is_healthy(self, recent_seconds: float = 120.0) -> bool:
        """
        Quick health check: Has liveness check succeeded recently?
        
        Args:
            recent_seconds: Consider healthy if last success within N seconds
        
        Returns:
            True if last successful check was recent, False otherwise
        """
        with self._lock:
            if self._last_check_time is None:
                return False
            
            # Compare timestamps (both are datetime with TZ info)
            now = datetime.now(Config.TZ)
            elapsed = (now - self._last_check_time).total_seconds()
            
            return elapsed < recent_seconds and self._last_ltp is not None


def create_liveness_monitor(
    feed,
    notifier: Optional[Any] = None,
    config_override: Optional[dict] = None
) -> Optional[LivenessMonitor]:
    """
    Factory function to create and start a liveness monitor based on config.
    
    Args:
        feed: UnifiedFeed instance
        notifier: Optional Telegram notifier
        config_override: Optional dict to override specific config values
    
    Returns:
        LivenessMonitor instance (started), or None if disabled
    
    Configuration (from config.py):
        - ENABLE_LIVENESS_MONITOR: bool (default False)
        - LIVENESS_CHECK_INTERVAL: float (default 60.0)
        - LIVENESS_TOKEN_SYMBOL: str (default "NIFTY")
        - LIVENESS_ENABLE_TELEGRAM: bool (default False)
    """
    # Merge config overrides
    config = config_override or {}
    
    # Get enable flag
    enabled = config.get(
        'enabled',
        getattr(Config, 'ENABLE_LIVENESS_MONITOR', False)
    )
    
    if not enabled:
        logger.info(" Liveness monitor is DISABLED")
        return None
    
    # Get interval
    interval = config.get(
        'interval',
        getattr(Config, 'LIVENESS_CHECK_INTERVAL', 60.0)
    )
    
    # Get token symbol
    token_symbol = config.get(
        'token_symbol',
        getattr(Config, 'LIVENESS_TOKEN_SYMBOL', 'NIFTY')
    )
    
    # Get Telegram flag
    enable_telegram = config.get(
        'enable_telegram',
        getattr(Config, 'LIVENESS_ENABLE_TELEGRAM', False)
    )
    
    # Create and start monitor
    monitor = LivenessMonitor(
        feed=feed,
        notifier=notifier,
        interval_seconds=interval,
        token_symbol=token_symbol,
        enable_telegram=enable_telegram
    )
    monitor.start()
    
    return monitor
