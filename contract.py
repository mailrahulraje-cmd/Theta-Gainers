#!/usr/bin/env python3
"""
Protocol definitions for type-safe interfaces across the trading system.

This file acts as the system-wide contract.
ALL brokers, feeds, and strategies must conform to these definitions.
"""

from typing import Protocol, Any, Dict, Optional, Callable, TypedDict, List
from datetime import datetime


# -------------------------------------------------------------------
# Type Aliases
# -------------------------------------------------------------------

# Tick callback signature: (token, symbol, ltp, timestamp, delta)
TickCallback = Callable[[Any, str, float, datetime, Optional[float]], None]


# -------------------------------------------------------------------
# Order / Trade data structures
# -------------------------------------------------------------------

class OrderDict(TypedDict, total=False):
    """
    Canonical order representation used across the system.
    Keep this stable  changing keys affects all brokers & strategies.
    """
    order_id: str
    symbol: str
    token: Any
    side: str               # BUY / SELL
    qty: int
    price: float
    trigger_price: float
    order_type: str         # MARKET / LIMIT / SL / SL-M
    product_type: str
    exchange: str
    status: str
    filled_qty: int
    avg_price: float
    timestamp: float
    remarks: str


# -------------------------------------------------------------------
# State protocol
# -------------------------------------------------------------------

class StateProtocol(Protocol):
    """Protocol for state management objects"""

    def get(self, key: str, default: Any = None) -> Any:
        ...

    def set(self, key: str, value: Any) -> None:
        ...

    def update(self, updates: Dict[str, Any]) -> None:
        ...


class StrategyStateProtocol(StateProtocol, Protocol):
    """
    Extended state protocol for strategy-specific operations.
    
    All lock methods return bool indicating whether the lock was
    newly acquired (True) or already held (False).
    
    CRITICAL: Implementers must ensure thread-safety via internal locks
    and atomic updates. State writes should use temp-file + atomic rename
    to prevent corruption on disk.
    """
    
    def lock_sell_ce_leg(self, payload: Dict[str, Any]) -> bool:
        """Lock SELL CE leg. Returns True if newly locked, False if already locked."""
        ...
    
    def lock_sell_pe_leg(self, payload: Dict[str, Any]) -> bool:
        """Lock SELL PE leg. Returns True if newly locked, False if already locked."""
        ...
    
    def lock_buy_ce_leg(self, payload: Dict[str, Any]) -> bool:
        """Lock BUY CE leg. Returns True if newly locked, False if already locked."""
        ...
    
    def lock_buy_pe_leg(self, payload: Dict[str, Any]) -> bool:
        """Lock BUY PE leg. Returns True if newly locked, False if already locked."""
        ...


# -------------------------------------------------------------------
# Feed protocol
# -------------------------------------------------------------------

class FeedProtocol(Protocol):
    """
    Protocol for market data feeds (live / replay)
    
    Tick callback signature: TickCallback(token, symbol, ltp, timestamp, delta)
    - token: Instrument token (Any type to support different broker formats)
    - symbol: Trading symbol as string
    - ltp: Last traded price as float
    - timestamp: Time of tick as datetime object
    - delta: Option delta as Optional[float] (None if not available)
    """

    def get_ltp(self, token: Any, check_freshness: bool = True) -> Optional[float]:
        ...

    def set_tick_callback(self, callback: TickCallback) -> None:
        """
        Set callback for incoming ticks.
        Callback must match TickCallback signature.
        """
        ...

    def subscribe(self, tokens: Any, symbol_map: Optional[Dict[str, str]] = None, 
                  exchange: Optional[str] = None) -> None:
        ...

    def close(self) -> None:
        ...


# -------------------------------------------------------------------
# Broker protocol
# -------------------------------------------------------------------

class BrokerProtocol(Protocol):
    """
    Protocol for broker objects.
    Both PaperBroker and LiveBroker must follow this.
    """

    def place_order(self, *args, **kwargs) -> OrderDict:
        ...

    def modify_order(self, *args, **kwargs) -> Any:
        ...

    def cancel_order(self, *args, **kwargs) -> Any:
        ...

    def get_positions(self) -> Any:
        ...

    def get_orders(self) -> Any:
        ...


# -------------------------------------------------------------------
# Notification protocol
# -------------------------------------------------------------------

class NotifierProtocol(Protocol):
    """
    Protocol for notification / alert systems.
    
    CRITICAL: At system startup, assert runtime conformance by checking
    that the notifier implementation has all required methods via hasattr()
    and callable() checks. This prevents silent failures when the notifier
    is incomplete or incorrectly initialized.
    
    Example:
        required_methods = ['send_trade_entry', 'send_phase_change', 'heartbeat', ...]
        for method in required_methods:
            assert hasattr(notifier, method) and callable(getattr(notifier, method))
    """

    def send_entry(self, label: str, price: float, token: Any = None,
                   strike: int = None, option_type: str = None,
                   qty: int = None, sl: float = None) -> None:
        ...

    def send_exit(
        self,
        message: str,
        price: float,
        pnl: float = 0.0,
        reason: str = "",
        token: Any = None
    ) -> None:
        ...

    def send_trade_log(self, message: str) -> None:
        ...

    def send_strike_selection(self, message: str) -> None:
        ...
    
    def send_phase_change(self, new_phase: str) -> None:
        ...
    
    def send_lock_event(self, sell_ce_strike: int, sell_ce_price: float,
                       sell_pe_strike: int, sell_pe_price: float,
                       buy_ce_strike: int, buy_ce_price: float,
                       buy_pe_strike: int, buy_pe_price: float) -> None:
        ...
    
    def send_trade_entry(self, sell_ce_strike: int, sell_ce_price: float, sell_ce_sl: float,
                        sell_pe_strike: int, sell_pe_price: float, sell_pe_sl: float) -> None:
        ...
    
    def send_trailing_sl_update(self, ce_strike: int, ce_sl: float,
                                pe_strike: int, pe_sl: float) -> None:
        ...

    def heartbeat(self, phase: str, pnl: float, pos_count: int, 
                 legs: Any = None) -> None:
        ...


# -------------------------------------------------------------------
# Trade Leg Data Model
# -------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TradeLegV1:
    """
    Type-safe representation of a single trade leg (position in one option contract).
    Used by TradeLegManager for type-safe leg storage and access.
    """
    token: Any  # Instrument token (broker-specific format)
    quantity: int = 0  # Position quantity
    side: str = 'UNKNOWN'  # BUY or SELL
    entry_price: float = 0.0  # Entry price when position opened
    timestamp: float = 0.0  # Entry timestamp (seconds since epoch)
    version: str = '1.0'  # Data format version
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'token': self.token,
            'quantity': self.quantity,
            'side': self.side,
            'entry_price': self.entry_price,
            'timestamp': self.timestamp,
            'version': self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradeLegV1':
        """Deserialize from dictionary."""
        return cls(
            token=data.get('token'),
            quantity=data.get('quantity', 0),
            side=data.get('side', 'UNKNOWN'),
            entry_price=data.get('entry_price', 0.0),
            timestamp=data.get('timestamp', 0.0),
            version=data.get('version', '1.0'),
        )

