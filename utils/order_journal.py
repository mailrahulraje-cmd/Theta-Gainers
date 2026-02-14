"""
Structured Order Journal - Forensic Audit Logging for Trading Execution

Logs all order events as JSON for post-trade analysis and forensic audit.
Supports: ENTRY, SL, RECON, EMERGENCY, HARD_EXIT events.
"""

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from config import Config


class OrderJournal:
    """
    Centralized structured logging for all order events.
    
    Thread-safe JSON logging with minimal performance impact.
    """
    
    def __init__(self, log_file: Optional[str] = None):
        """
        Initialize order journal.
        
        Args:
            log_file: Path to append-mode log file. 
                     Defaults to: {PROJECT_ROOT}/order_journal.log
        """
        if log_file is None:
            log_file = str(Config.BASE_DIR / "order_journal.log")
        
        self.log_file = log_file
        self.lock = threading.Lock()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Ensure log file exists and is writable"""
        try:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            # Create or truncate file
            with open(self.log_file, 'a', encoding='utf-8') as f:
                pass  # Just ensure file exists
        except Exception as e:
            import logging
            logging.error(f"Failed to initialize order journal: {e}")
    
    def log_order_event(
        self,
        action: str,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        broker_order_id: Optional[str] = None,
        retry_count: int = 0,
        status: str = "SUBMITTED",
        details: Optional[Dict[str, Any]] = None,
        tag: str = ""
    ):
        """
        Log an order event with structured JSON.
        
        Args:
            action: One of: ENTRY, SL, RECON, EMERGENCY, HARD_EXIT, EXIT
            symbol: Trading symbol (e.g., NIFTY25FEB24500CE)
            strike: Strike price
            qty: Order quantity (negative for SELL)
            price: Order price
            broker_order_id: Exchange order ID if available
            retry_count: Number of retries attempted
            status: Order status (SUBMITTED, FILLED, REJECTED, PARTIAL, etc.)
            details: Additional context dict (optional)
            tag: Custom tag for grouping/filtering (e.g., "SELL_CE_ENTRY")
        """
        try:
            with self.lock:
                event = {
                    'timestamp': datetime.now(Config.TZ).isoformat(),
                    'timestamp_monotonic': time.monotonic(),
                    'action': action.upper(),
                    'symbol': str(symbol),
                    'strike': int(strike) if strike is not None else None,
                    'qty': int(qty),
                    'price': float(price),
                    'broker_order_id': broker_order_id,
                    'retry_count': int(retry_count),
                    'status': status.upper(),
                    'tag': str(tag) if tag else "",
                    'details': details or {}
                }
                
                # Append to log file
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event) + '\n')
                
        except Exception as e:
            import logging
            logging.error(f"Failed to log order event: {e}")
    
    def log_entry(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        broker_order_id: Optional[str] = None,
        tag: str = ""
    ):
        """Log a trade entry"""
        self.log_order_event(
            action='ENTRY',
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            broker_order_id=broker_order_id,
            status='FILLED',
            tag=tag
        )
    
    def log_exit(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        exit_type: str = "SL",  # SL, TP, MANUAL, SQUAREOFF
        broker_order_id: Optional[str] = None
    ):
        """Log a trade exit"""
        self.log_order_event(
            action=exit_type.upper(),
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            broker_order_id=broker_order_id,
            status='FILLED',
            tag=f"EXIT_{exit_type.upper()}"
        )
    
    def log_reconciliation(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        mismatch_type: str = "QTY",  # QTY, PRICE, BOTH
        details: Optional[Dict] = None
    ):
        """Log a reconciliation event (broker vs internal mismatch"""
        details = details or {}
        details['mismatch_type'] = mismatch_type
        self.log_order_event(
            action='RECON',
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            status='MISMATCH' if mismatch_type != 'NONE' else 'OK',
            details=details,
            tag='RECONCILIATION'
        )
    
    def log_emergency(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        reason: str = "UNKNOWN"
    ):
        """Log an emergency flatten event"""
        self.log_order_event(
            action='EMERGENCY',
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            status='EMERGENCY_EXIT',
            details={'reason': reason},
            tag='EMERGENCY_FLATTEN'
        )
    
    def log_hard_exit(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float
    ):
        """Log a hard exit event (market close enforcement)"""
        self.log_order_event(
            action='HARD_EXIT',
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            status='HARD_EXIT_CLOSE',
            tag='MARKET_CLOSE_ENFORCEMENT'
        )
    
    def log_rejection(
        self,
        symbol: str,
        strike: int,
        qty: int,
        price: float,
        reason: str = "UNKNOWN",
        action: str = "ENTRY",
        tag: str = ""
    ):
        """Log a rejected order"""
        self.log_order_event(
            action=action,
            symbol=symbol,
            strike=strike,
            qty=qty,
            price=price,
            status='REJECTED',
            details={'rejection_reason': reason},
            tag=tag
        )
    
    def get_log_file(self) -> str:
        """Get the path to the order journal log file"""
        return self.log_file


# Global singleton instance
_journal_instance = None
_journal_lock = threading.Lock()


def get_order_journal() -> OrderJournal:
    """Get or create global order journal instance (thread-safe)."""
    global _journal_instance
    if _journal_instance is None:
        with _journal_lock:
            if _journal_instance is None:
                _journal_instance = OrderJournal()
    return _journal_instance
