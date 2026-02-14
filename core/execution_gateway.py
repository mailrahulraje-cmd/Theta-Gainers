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
    
    def validate_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "MARKET",
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
            
        Returns:
            (allowed, reason) - allowed=True if passes, reason if blocked
        """
        self._reset_daily_tracking_if_needed()
        
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
