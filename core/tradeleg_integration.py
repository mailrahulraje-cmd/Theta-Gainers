#!/usr/bin/env python3
"""
TradeLegV1 Integration Layer for Trading System

Provides type-safe wrappers around broker interactions and leg management.
Ensures all broker operations work with TradeLegV1 instances while maintaining
backward compatibility with legacy code.

Key Patterns:
- get_leg() → TradeLegV1 or None
- set_leg() → validates + saves to state
- All broker interactions wrapped in try/except
- Thread-safe access to TradeLegManager
"""

import logging
import threading
from typing import Dict, Optional, Any, Callable
from datetime import datetime
from contract import TradeLegV1
from core.state import StrategyState

logger = logging.getLogger(__name__)


class TradeLegAPIWrapper:
    """
    Safe, type-checked API for all trade leg operations.
    
    Replaces raw dict access throughout the system:
    
    OLD (fragile):
        token = state.state['sell_ce_token']  # KeyError possible
        price = state.state['sell_ce_ref_premium']
    
    NEW (safe):
        leg = state.get_leg('sell_ce')
        if leg:
            token = leg.token
            price = leg.entry_price
    """
    
    def __init__(self, state: StrategyState):
        """
        Args:
            state: StrategyState instance with TradeLegManager
        """
        self.state = state
        self._lock = threading.RLock()  # Reentrant lock for safety
    
    def get_leg_safe(self, leg_name: str) -> Optional[TradeLegV1]:
        """
        Safely retrieve a leg with error handling.
        
        Args:
            leg_name: "sell_ce", "sell_pe", "buy_ce", "buy_pe"
        
        Returns:
            TradeLegV1 or None if not found
        
        Example:
            leg = api.get_leg_safe("sell_ce")
            if leg:
                print(f"Entry price: {leg.entry_price}")
        """
        try:
            with self._lock:
                return self.state.get_leg(leg_name)
        except Exception as e:
            logger.error(f"Failed to retrieve leg '{leg_name}': {e}")
            return None
    
    def set_leg_safe(self, leg_name: str, leg: TradeLegV1) -> bool:
        """
        Safely store a leg with validation.
        
        Args:
            leg_name: Leg name
            leg: TradeLegV1 instance
        
        Returns:
            True if successful, False if error
        
        Example:
            leg = TradeLegV1(token="50000CE", entry_price=50.0, ...)
            if api.set_leg_safe("sell_ce", leg):
                logger.info("Leg saved successfully")
        """
        try:
            with self._lock:
                self.state.set_leg(leg_name, leg)
                logger.debug(f"Set leg '{leg_name}': {leg}")
                return True
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to set leg '{leg_name}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error setting leg '{leg_name}': {e}")
            return False
    
    def create_leg_from_entry(
        self,
        leg_name: str,
        token: str,
        entry_price: float,
        quantity: int,
        side: str,
        timestamp: Optional[str] = None
    ) -> Optional[TradeLegV1]:
        """
        Create a TradeLegV1 instance with validation.
        
        Args:
            leg_name: "sell_ce", "sell_pe", "buy_ce", "buy_pe"
            token: Instrument token
            entry_price: Entry price (must be > 0)
            quantity: Number of contracts (must be > 0)
            side: "SELL" or "BUY"
            timestamp: ISO format timestamp (defaults to now)
        
        Returns:
            TradeLegV1 instance or None if invalid
        
        Example:
            leg = api.create_leg_from_entry(
                "sell_ce", "50000CE", 50.0, 1, "SELL"
            )
            if leg:
                api.set_leg_safe("sell_ce", leg)
        """
        try:
            if timestamp is None:
                timestamp = datetime.now().isoformat()
            
            leg = TradeLegV1(
                token=str(token),
                entry_price=float(entry_price),
                quantity=int(quantity),
                side=side.upper(),
                timestamp=timestamp,
                leg_id=f"{leg_name.upper()}_{int(datetime.now().timestamp())}",
                status="OPEN"
            )
            logger.debug(f"Created leg: {leg}")
            return leg
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to create leg '{leg_name}': {e}")
            return None
    
    def mark_leg_closed(
        self,
        leg_name: str,
        exit_price: float,
        pnl: float
    ) -> bool:
        """
        Mark a leg as closed with exit price and PnL.
        
        Args:
            leg_name: Leg name
            exit_price: Exit price (must be > 0)
            pnl: Profit/loss amount
        
        Returns:
            True if updated, False otherwise
        
        Example:
            api.mark_leg_closed("sell_ce", 48.5, 150.0)
        """
        try:
            leg = self.get_leg_safe(leg_name)
            if not leg:
                logger.error(f"Leg '{leg_name}' not found")
                return False
            
            # Create updated leg with closed status
            closed_leg = TradeLegV1(
                token=leg.token,
                entry_price=leg.entry_price,
                quantity=leg.quantity,
                side=leg.side,
                timestamp=leg.timestamp,
                leg_id=leg.leg_id,
                status="CLOSED",
                exit_price=float(exit_price),
                pnl=float(pnl)
            )
            
            return self.set_leg_safe(leg_name, closed_leg)
        except Exception as e:
            logger.error(f"Failed to mark leg '{leg_name}' as closed: {e}")
            return False
    
    def get_active_legs_summary(self) -> str:
        """
        Get human-readable summary of all active legs.
        
        Returns:
            Multi-line string with leg information
        """
        return self.state.leg_summary()
    
    def verify_leg_integrity(self, leg_name: str) -> bool:
        """
        Verify a leg's data integrity (checksum).
        
        Args:
            leg_name: Leg name
        
        Returns:
            True if verified, False if corrupted or missing
        """
        try:
            with self._lock:
                if not self.state.leg_manager.has_leg(leg_name):
                    logger.warning(f"Leg '{leg_name}' not found for integrity check")
                    return False
                
                # Verify checksum
                leg = self.state.leg_manager.get_leg(leg_name)
                stored_checksum = self.state.leg_manager.checksums.get(leg_name)
                
                if not stored_checksum:
                    logger.warning(f"No checksum for leg '{leg_name}'")
                    return False
                
                computed_checksum = leg.compute_checksum()
                is_valid = computed_checksum == stored_checksum
                
                if not is_valid:
                    logger.error(
                        f"Leg '{leg_name}' integrity check FAILED: "
                        f"stored={stored_checksum[:16]}..., "
                        f"computed={computed_checksum[:16]}..."
                    )
                else:
                    logger.debug(f"Leg '{leg_name}' integrity verified ✓")
                
                return is_valid
        except Exception as e:
            logger.error(f"Integrity check failed for '{leg_name}': {e}")
            return False
    
    def get_legs_dict_for_export(self) -> Dict[str, Dict[str, Any]]:
        """
        Export all legs as dictionaries (for CSV/JSON).
        
        Returns:
            {
                "sell_ce": {...leg_dict...},
                "sell_pe": {...leg_dict...},
                ...
            }
        """
        try:
            result = {}
            for leg_name in self.state.get_active_legs():
                leg = self.get_leg_safe(leg_name)
                if leg:
                    result[leg_name] = leg.to_dict()
            return result
        except Exception as e:
            logger.error(f"Failed to export legs: {e}")
            return {}


class BrokerInteractionWrapper:
    """
    Wraps all broker interactions with TradeLegV1-aware error handling.
    
    Ensures:
    - All orders read from TradeLegV1 fields
    - All updates write to TradeLegV1 instances
    - Proper error handling and logging
    - Thread-safe concurrent access
    """
    
    def __init__(self, broker, leg_api: TradeLegAPIWrapper):
        """
        Args:
            broker: PaperBroker or LiveBroker instance
            leg_api: TradeLegAPIWrapper instance
        """
        self.broker = broker
        self.leg_api = leg_api
        self._lock = threading.RLock()
    
    def place_order_from_leg(
        self,
        leg_name: str,
        leg: TradeLegV1,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Place an order using TradeLegV1 fields.
        
        Args:
            leg_name: Leg identifier
            leg: TradeLegV1 instance
            **kwargs: Additional parameters for broker.place_order()
        
        Returns:
            Order dict from broker or None if error
        
        Example:
            leg = state.get_leg("sell_ce")
            order = broker_api.place_order_from_leg("sell_ce", leg)
            if order:
                logger.info(f"Order placed: {order['order_id']}")
        """
        try:
            with self._lock:
                if not leg:
                    logger.error(f"Cannot place order for '{leg_name}': leg is None")
                    return None
                
                # Use leg fields to construct order
                order = self.broker.place_order(
                    side=leg.side,
                    token=leg.token,
                    qty=leg.quantity,
                    price=leg.entry_price,
                    tag=leg.leg_id,
                    **kwargs
                )
                
                logger.info(
                    f"Order placed for {leg_name}: "
                    f"{leg.side} {leg.quantity} @ {leg.entry_price} "
                    f"(id={order.get('order_id')})"
                )
                
                return order
        except Exception as e:
            logger.error(
                f"Failed to place order for '{leg_name}': {e}",
                exc_info=True
            )
            return None
    
    def update_leg_from_fill(
        self,
        leg_name: str,
        fill_price: float,
        fill_qty: int
    ) -> bool:
        """
        Update leg with fill information.
        
        Args:
            leg_name: Leg identifier
            fill_price: Actual fill price
            fill_qty: Actual quantity filled
        
        Returns:
            True if updated successfully
        """
        try:
            with self._lock:
                leg = self.leg_api.get_leg_safe(leg_name)
                if not leg:
                    logger.error(f"Cannot update '{leg_name}': leg not found")
                    return False
                
                # Create updated leg with actual fill price
                updated_leg = TradeLegV1(
                    token=leg.token,
                    entry_price=fill_price,  # Use actual fill price
                    quantity=fill_qty,       # Update with actual quantity
                    side=leg.side,
                    timestamp=leg.timestamp,
                    leg_id=leg.leg_id,
                    status="OPEN"
                )
                
                return self.leg_api.set_leg_safe(leg_name, updated_leg)
        except Exception as e:
            logger.error(f"Failed to update leg '{leg_name}' from fill: {e}")
            return False
    
    def close_leg_from_exit(
        self,
        leg_name: str,
        exit_price: float,
        exit_qty: int,
        exit_order_id: str = ""
    ) -> bool:
        """
        Mark leg as closed with exit information.
        
        Args:
            leg_name: Leg identifier
            exit_price: Exit price achieved
            exit_qty: Quantity exited
            exit_order_id: Order ID of exit (for audit)
        
        Returns:
            True if closed successfully
        """
        try:
            with self._lock:
                leg = self.leg_api.get_leg_safe(leg_name)
                if not leg:
                    logger.error(f"Cannot close '{leg_name}': leg not found")
                    return False
                
                # Calculate PnL
                if leg.side == "SELL":
                    pnl = (leg.entry_price - exit_price) * exit_qty * 100  # Typical lot size
                else:
                    pnl = (exit_price - leg.entry_price) * exit_qty * 100
                
                # Create closed leg
                closed_leg = TradeLegV1(
                    token=leg.token,
                    entry_price=leg.entry_price,
                    quantity=exit_qty,
                    side=leg.side,
                    timestamp=leg.timestamp,
                    leg_id=leg.leg_id,
                    status="CLOSED",
                    exit_price=exit_price,
                    pnl=pnl
                )
                
                logger.info(
                    f"Closed {leg_name}: "
                    f"{leg.side} {exit_qty} @ exit {exit_price} "
                    f"| PnL = {pnl:+.2f}"
                )
                
                return self.leg_api.set_leg_safe(leg_name, closed_leg)
        except Exception as e:
            logger.error(f"Failed to close leg '{leg_name}': {e}")
            return False


class ConcurrentLegAccessor:
    """
    Thread-safe accessor for TradeLegV1 instances.
    
    Used when multiple threads need concurrent read/write access.
    Wraps all operations in locks to prevent race conditions.
    """
    
    def __init__(self, leg_api: TradeLegAPIWrapper):
        """
        Args:
            leg_api: TradeLegAPIWrapper instance
        """
        self.leg_api = leg_api
        self._lock = threading.RLock()
    
    def get_leg_exclusive(self, leg_name: str) -> Optional[TradeLegV1]:
        """
        Get leg with exclusive lock (for read + immediate write).
        
        Args:
            leg_name: Leg name
        
        Returns:
            TradeLegV1 or None
        """
        with self._lock:
            return self.leg_api.get_leg_safe(leg_name)
    
    def update_leg_atomic(
        self,
        leg_name: str,
        updater: Callable[[TradeLegV1], TradeLegV1]
    ) -> bool:
        """
        Atomically read and update a leg.
        
        Args:
            leg_name: Leg name
            updater: Function that takes TradeLegV1 and returns updated TradeLegV1
        
        Returns:
            True if updated, False if leg not found
        
        Example:
            def mark_entered(leg):
                return TradeLegV1(
                    ...leg fields...,
                    status="ENTERED"
                )
            
            accessor.update_leg_atomic("sell_ce", mark_entered)
        """
        try:
            with self._lock:
                leg = self.leg_api.get_leg_safe(leg_name)
                if not leg:
                    return False
                
                updated = updater(leg)
                return self.leg_api.set_leg_safe(leg_name, updated)
        except Exception as e:
            logger.error(f"Atomic update failed for '{leg_name}': {e}")
            return False
    
    def batch_verify_all(self) -> Dict[str, bool]:
        """
        Verify integrity of all legs atomically.
        
        Returns:
            {leg_name: is_valid, ...}
        """
        try:
            with self._lock:
                result = {}
                for leg_name in self.leg_api.state.get_active_legs():
                    result[leg_name] = self.leg_api.verify_leg_integrity(leg_name)
                return result
        except Exception as e:
            logger.error(f"Batch verification failed: {e}")
            return {}
