"""
Execution Gateway - Centralized Order Validation and Safety Enforcement

CRITICAL: All order placement MUST go through this gateway.
Both PaperBroker and LiveBroker integrate this for consistent safety.
"""

import threading
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from config import Config
from utils.logger import logger


class OrderRateLimiter:
    """Thread-safe rate limiter for order placement"""
    
    def __init__(self, max_orders_per_minute: int):
        self.max_orders = max_orders_per_minute
        self.order_timestamps = []
        self.lock = threading.Lock()
    
    def can_place_order(self) -> Tuple[bool, Optional[str]]:
        """
        Check if an order can be placed without exceeding rate limits.
        
        Returns:
            (allowed, reason) - allowed=True if order can be placed, reason if not
        """
        with self.lock:
            now = time.time()
            # Remove timestamps older than 1 minute
            cutoff = now - 60.0
            self.order_timestamps = [ts for ts in self.order_timestamps if ts > cutoff]
            
            if len(self.order_timestamps) >= self.max_orders:
                return False, f"Rate limit: {len(self.order_timestamps)}/{self.max_orders} orders/min"
            
            # Record this order attempt
            self.order_timestamps.append(now)
            return True, None


class ExecutionGateway:
    """
    Centralized execution gateway enforcing all safety checks.
    
    This is a CRITICAL SAFETY COMPONENT - do not bypass.
    """
    
    def __init__(self):
        self.rate_limiter = OrderRateLimiter(Config.MAX_ORDERS_PER_MINUTE)
        self.lock = threading.Lock()
        
        # Track daily P&L for circuit breaker
        self._daily_pnl = 0.0
        self._last_pnl_reset = datetime.now().date()
        
        # Feed circuit breaker support
        self.feed = None
        self._last_feed_alert_state = None  # Track last alert to avoid spam
        self._feed_state_change_time = None  # Track when feed state last changed
        
        # Optional notifier for alerts
        self.notifier = None
        
        logger.info("="*70)
        logger.info(" EXECUTION GATEWAY INITIALIZED")
        logger.info("="*70)
        logger.info(f"Rate Limit: {Config.MAX_ORDERS_PER_MINUTE} orders/minute")
        logger.info(f"Max Daily Loss: {Config.MAX_DAILY_LOSS}")
        logger.info(f"Circuit Breaker: {'ENABLED' if Config.ENABLE_CIRCUIT_BREAKER else 'DISABLED'}")
        logger.info(f"Kill Switch: {'ACTIVE' if Config.KILL_SWITCH_ENABLED else 'OFF'}")
        logger.info(f"No New Trades: {'YES' if Config.NO_NEW_TRADES else 'NO'}")
        logger.info("="*70)
    
    def _reset_daily_tracking_if_needed(self):
        """Reset daily counters on new trading day"""
        today = datetime.now().date()
        if today != self._last_pnl_reset:
            logger.info(f" New trading day - resetting daily P&L tracking")
            self._daily_pnl = 0.0
            self._last_pnl_reset = today
    
    def set_feed(self, feed):
        """
        Set the feed object for health status checking.
        Call this after ExecutionGateway initialization.
        
        Args:
            feed: UnifiedFeed instance with get_health_status() method
        """
        with self.lock:
            self.feed = feed
            if feed:
                logger.info(" ExecutionGateway: Feed circuit breaker ENABLED")
            else:
                logger.warning(" ExecutionGateway: Feed object not set - feed checks disabled")
    
    def set_notifier(self, notifier):
        """
        Set the notifier for sending feed alert messages.
        Optional: enables Telegram notifications for feed state changes.
        
        Args:
            notifier: Notifier instance with send_trade_log() method
        """
        with self.lock:
            self.notifier = notifier
            if notifier:
                logger.info(" ExecutionGateway: Telegram feed alerts ENABLED")
            else:
                logger.info(" ExecutionGateway: Telegram feed alerts DISABLED")
    
    def _check_feed_health(self, is_entry: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Check feed health status and block orders if necessary.
        
        Blocking Rules:
        - DEAD feed: Block ALL orders (entry + exit)
        - CRITICAL feed: Block NEW ENTRIES only (allow exits, SL, risk-reduction)
        - DEGRADED/OK: Allow all orders
        
        Args:
            is_entry: Whether this is a entry order (True) or exit (False)
        
        Returns:
            (allowed, reason) - allowed=True if passes, reason if blocked
        """
        # Skip if feed not configured
        if not self.feed:
            return True, None
        
        try:
            feed_status, metadata = self.feed.get_health_status()
            status = feed_status.upper()
            
            # Track state changes to send alerts once per state change
            state_changed = status != self._last_feed_alert_state
            if state_changed:
                with self.lock:
                    self._last_feed_alert_state = status
                    self._feed_state_change_time = time.time()
                
                # Send Telegram alert on state change (asynchronously to avoid blocking)
                if self.notifier:
                    try:
                        if status == "DEAD":
                            msg = "🔴 FEED DEAD - All orders blocked"
                        elif status == "CRITICAL":
                            msg = "🟠 FEED CRITICAL - New entries blocked"
                        elif status == "DEGRADED":
                            msg = "🟡 FEED DEGRADED - Monitoring closely"
                        else:  # OK
                            msg = "🟢 FEED RECOVERED - Trading resumed"
                        
                        # Send alert asynchronously
                        threading.Thread(
                            target=self.notifier.send_trade_log,
                            args=(msg,),
                            daemon=True
                        ).start()
                    except Exception as e:
                        logger.exception(f"Failed to send feed alert: {e}")
            
            # 🔴 DEAD feed → block ALL orders
            if status == "DEAD":
                logger.error(f"🚫 ORDER BLOCKED: Feed DEAD - {metadata}")
                return False, f"Feed DEAD - blocking all orders ({metadata})"
            
            # 🟠 CRITICAL feed → block NEW entries only
            if status == "CRITICAL" and is_entry:
                logger.warning(f"⚠️ ENTRY BLOCKED: Feed CRITICAL - {metadata}")
                return False, f"Feed CRITICAL - blocking new entries ({metadata})"
            
            # Allow other orders (exits, SL, risk-reduction)
        
        except Exception as e:
            logger.exception(f"Error checking feed health: {e}")
            # Fail safe: allow order if health check fails
            return True, None
        
        return True, None
    
    @staticmethod
    def infer_is_entry(symbol: str, transaction_type: str, 
                       positions: Optional[Dict[str, Any]] = None) -> bool:
        """
        Infer whether an order is likely an entry or exit.
        
        Logic:
        - No existing position → likely entry
        - Existing position with same side → likely exit/add
        - Existing position with opposite side → likely exit
        - If no position data available → default to False (conservative: treat as exit)
        
        Args:
            symbol: Trading symbol
            transaction_type: 'BUY' or 'SELL'
            positions: Dict of token->position info
        
        Returns:
            True if likely entry, False if likely exit
        """
        if positions is None:
            # No position data - default to False (conservative: assume exit)
            return False
        
        # Normalize symbol (remove Token- prefix if present)
        token = symbol.replace('Token-', '') if 'Token-' in symbol else symbol
        
        # If no position exists for this symbol, it's an entry
        if token not in positions:
            return True
        
        pos = positions[token]
        current_qty = pos.get('qty', 0)
        
        # No current position (might be closed) → entry
        if current_qty == 0:
            return True
        
        # Position exists with non-zero quantity → exit (or add to existing)
        # Conservative: treat as exit since we're likely closing or reducing
        return False
    
    def validate_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "MARKET",
        is_entry: bool = False,
        **kwargs
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate order against ALL safety checks.
        
        Args:
            symbol: Trading symbol
            transaction_type: 'BUY' or 'SELL'
            quantity: Order quantity
            price: Limit price (if applicable)
            order_type: 'MARKET' or 'LIMIT'
            is_entry: Whether this is a new entry order (default False for exits)
            
        Returns:
            (allowed, reason) - allowed=True if passes, reason if blocked
        """
        self._reset_daily_tracking_if_needed()
        
        # ============================================================
        # CHECK 0: FEED HEALTH (HIGHEST PRIORITY - Before Kill Switch)
        # ============================================================
        # Feed degradation/death is a critical real-time condition
        feed_ok, feed_reason = self._check_feed_health(is_entry=is_entry)
        if not feed_ok:
            return False, feed_reason
        
        # ============================================================
        # CHECK 1: KILL SWITCH (HIGHEST PRIORITY)
        # ============================================================
        if Config.KILL_SWITCH_ENABLED:
            logger.error(" KILL SWITCH ACTIVE - All trading halted")
            return False, "KILL SWITCH ACTIVE - All trading halted"
        
        if Config.NO_NEW_TRADES:
            logger.warning(" NO_NEW_TRADES mode - Blocking new entries")
            return False, "NO_NEW_TRADES active - Only exits allowed"
        
        if Config.EMERGENCY_EXIT_ALL:
            # Only allow exit orders
            if transaction_type not in ['EXIT', 'CLOSE']:
                return False, "EMERGENCY_EXIT_ALL active - Only position exits allowed"
        
        # ============================================================
        # CHECK 2: RATE LIMITING
        # ============================================================
        rate_ok, rate_reason = self.rate_limiter.can_place_order()
        if not rate_ok:
            logger.warning(f" Order blocked by rate limiter: {rate_reason}")
            return False, rate_reason
        
        # ============================================================
        # CHECK 3: ORDER VALIDATION
        # ============================================================
        if Config.ENABLE_ORDER_VALIDATION:
            # Validate quantity
            if quantity <= 0:
                return False, f"Invalid quantity: {quantity}"
            
            if quantity > Config.MAX_ORDER_QUANTITY:
                return False, f"Quantity {quantity} exceeds max {Config.MAX_ORDER_QUANTITY}"
            
            # Validate price for LIMIT orders
            if order_type == "LIMIT":
                if price is None or price <= 0:
                    return False, f"Invalid limit price: {price}"
        
        # ============================================================
        # CHECK 4: CIRCUIT BREAKER (Daily Loss Limit)
        # ============================================================
        if Config.ENABLE_CIRCUIT_BREAKER:
            with self.lock:
                if self._daily_pnl <= -Config.MAX_DAILY_LOSS:
                    logger.error(
                        f" CIRCUIT BREAKER TRIGGERED\n"
                        f"   Daily Loss: {abs(self._daily_pnl):.2f}\n"
                        f"   Max Allowed: {Config.MAX_DAILY_LOSS}\n"
                        f"   ALL TRADING HALTED"
                    )
                    return False, f"Circuit breaker: Daily loss {abs(self._daily_pnl):.2f}"
        
        # ============================================================
        # All checks passed
        # ============================================================
        return True, None
    
    def update_daily_pnl(self, pnl_change: float):
        """
        Update daily P&L tracking for circuit breaker.
        Call when positions are closed or P&L realized.
        """
        self._reset_daily_tracking_if_needed()
        
        with self.lock:
            self._daily_pnl += pnl_change
            
            # Warning at 80% of limit
            if self._daily_pnl <= -Config.MAX_DAILY_LOSS * 0.8:
                logger.warning(
                    f" APPROACHING DAILY LOSS LIMIT\n"
                    f"   Current: {abs(self._daily_pnl):.2f}\n"
                    f"   Limit: {Config.MAX_DAILY_LOSS}\n"
                    f"   Remaining: {Config.MAX_DAILY_LOSS - abs(self._daily_pnl):.2f}"
                )
    
    def get_daily_pnl(self) -> float:
        """Get current daily P&L"""
        self._reset_daily_tracking_if_needed()
        with self.lock:
            return self._daily_pnl


# ============================================================================
# SINGLETON PATTERN - System-wide single instance
# ============================================================================

_gateway_instance: Optional[ExecutionGateway] = None
_gateway_lock = threading.Lock()


def get_execution_gateway() -> ExecutionGateway:
    """
    Get singleton ExecutionGateway instance.
    Thread-safe singleton pattern with double-check locking.
    """
    global _gateway_instance
    
    if _gateway_instance is None:
        with _gateway_lock:
            if _gateway_instance is None:  # Double-check
                _gateway_instance = ExecutionGateway()
    
    return _gateway_instance
