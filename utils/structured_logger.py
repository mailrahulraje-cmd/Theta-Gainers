"""
Production-grade structured CSV logging system

Implements:
- Trade logging (entry, exit, squareoff) to daily rotated CSV
- Locked reference logging (spot, ATM, strikes, deltas, premiums) to CSV
- Consistent token/symbol mapping across all logs
- Daily file rotation
- Thread-safe operations
"""
import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class StructuredLogger:
    """
    Production-grade CSV logger for trading system
    Separate files for trades and locked references
    """
    
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        
        # Track current date for rotation
        self._current_date = datetime.now().strftime("%Y%m%d")
        
        # Initialize CSV files
        self._init_trade_log()
        self._init_lock_log()
        
        logger.info(f"StructuredLogger initialized: {self.log_dir}")
    
    # -------------------------
    # File initialization
    # -------------------------
    def _get_trade_log_path(self) -> Path:
        """Get path for today's trade log"""
        return self.log_dir / f"trades_{self._current_date}.csv"
    
    def _get_lock_log_path(self) -> Path:
        """Get path for today's lock log"""
        return self.log_dir / f"locks_{self._current_date}.csv"
    
    def _init_trade_log(self):
        """Initialize trade log CSV with headers"""
        path = self._get_trade_log_path()
        if not path.exists():
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'event_type',  # ENTRY, EXIT, SQUAREOFF
                    'token',
                    'symbol',
                    'strike',
                    'option_type',  # CE/PE
                    'side',  # BUY/SELL
                    'quantity',
                    'price',
                    'phase',
                    'reason',
                    'pnl',
                    'tag'
                ])
            logger.info(f"Created trade log: {path}")
    
    def _init_lock_log(self):
        """Initialize lock reference log CSV with headers"""
        path = self._get_lock_log_path()
        if not path.exists():
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'phase',
                    'lock_type',  # PHASE0_LOCK, PHASE1_LOCK
                    'spot_price',
                    'atm_strike',
                    'sell_ce_token',
                    'sell_ce_symbol',
                    'sell_ce_strike',
                    'sell_ce_premium',
                    'sell_pe_token',
                    'sell_pe_symbol',
                    'sell_pe_strike',
                    'sell_pe_premium',
                    'otm_ce_token',
                    'otm_ce_symbol',
                    'otm_ce_strike',
                    'otm_ce_delta',
                    'otm_ce_premium',
                    'otm_pe_token',
                    'otm_pe_symbol',
                    'otm_pe_strike',
                    'otm_pe_delta',
                    'otm_pe_premium'
                ])
            logger.info(f"Created lock log: {path}")
    
    def _check_rotation(self):
        """Check if date changed and rotate files if needed"""
        current = datetime.now().strftime("%Y%m%d")
        if current != self._current_date:
            logger.info(f"Date changed: {self._current_date} -> {current}. Rotating logs.")
            self._current_date = current
            self._init_trade_log()
            self._init_lock_log()
    
    # -------------------------
    # Trade logging
    # -------------------------
    def log_trade(self, 
                  event_type: str,
                  token: str,
                  symbol: str,
                  strike: int,
                  option_type: str,
                  side: str,
                  quantity: int,
                  price: float,
                  phase: str,
                  reason: str = "",
                  pnl: Optional[float] = None,
                  tag: str = ""):
        """
        Log a trade event to CSV
        
        Args:
            event_type: ENTRY, EXIT, SQUAREOFF
            token: Contract token
            symbol: Trading symbol
            strike: Strike price
            option_type: CE or PE
            side: BUY or SELL
            quantity: Number of lots
            price: Execution price
            phase: Strategy phase (PHASE0, PHASE1, etc.)
            reason: Exit reason (SL, TP, SQUAREOFF, etc.)
            pnl: P&L for exits
            tag: Additional tag
        """
        with self._lock:
            self._check_rotation()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            with open(self._get_trade_log_path(), 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    event_type,
                    token,
                    symbol,
                    strike,
                    option_type,
                    side,
                    quantity,
                    f"{price:.2f}",
                    phase,
                    reason,
                    f"{pnl:.2f}" if pnl is not None else "",
                    tag
                ])
            
            logger.info(
                f"TRADE_LOG: {event_type} {symbol} {side} {quantity} @ {price:.2f} "
                f"[{phase}] {reason}"
            )
    
    # -------------------------
    # Lock reference logging
    # -------------------------
    def log_lock(self,
                 phase: str,
                 lock_type: str,
                 spot_price: float,
                 atm_strike: int,
                 sell_ce: Optional[Dict[str, Any]] = None,
                 sell_pe: Optional[Dict[str, Any]] = None,
                 otm_ce: Optional[Dict[str, Any]] = None,
                 otm_pe: Optional[Dict[str, Any]] = None):
        """
        Log locked references to CSV
        
        Args:
            phase: PHASE0 or PHASE1
            lock_type: PHASE0_LOCK or PHASE1_LOCK
            spot_price: Spot price at lock time
            atm_strike: ATM strike at lock time
            sell_ce: {token, symbol, strike, premium, delta}
            sell_pe: {token, symbol, strike, premium, delta}
            otm_ce: {token, symbol, strike, premium, delta}
            otm_pe: {token, symbol, strike, premium, delta}
        """
        with self._lock:
            self._check_rotation()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            def get_field(leg: Optional[Dict], field: str, default=""):
                if leg and field in leg:
                    val = leg[field]
                    if isinstance(val, float):
                        return f"{val:.4f}" if field == 'delta' else f"{val:.2f}"
                    return str(val)
                return default
            
            with open(self._get_lock_log_path(), 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    phase,
                    lock_type,
                    f"{spot_price:.2f}",
                    atm_strike,
                    # SELL CE
                    get_field(sell_ce, 'token'),
                    get_field(sell_ce, 'symbol'),
                    get_field(sell_ce, 'strike'),
                    get_field(sell_ce, 'premium'),
                    # SELL PE
                    get_field(sell_pe, 'token'),
                    get_field(sell_pe, 'symbol'),
                    get_field(sell_pe, 'strike'),
                    get_field(sell_pe, 'premium'),
                    # OTM CE
                    get_field(otm_ce, 'token'),
                    get_field(otm_ce, 'symbol'),
                    get_field(otm_ce, 'strike'),
                    get_field(otm_ce, 'delta'),
                    get_field(otm_ce, 'premium'),
                    # OTM PE
                    get_field(otm_pe, 'token'),
                    get_field(otm_pe, 'symbol'),
                    get_field(otm_pe, 'strike'),
                    get_field(otm_pe, 'delta'),
                    get_field(otm_pe, 'premium')
                ])
            
            logger.info(
                f"LOCK_LOG: {lock_type} Spot={spot_price:.2f} ATM={atm_strike} "
                f"SELL_CE={get_field(sell_ce, 'strike')} SELL_PE={get_field(sell_pe, 'strike')} "
                f"OTM_CE={get_field(otm_ce, 'strike')}{get_field(otm_ce, 'delta')} "
                f"OTM_PE={get_field(otm_pe, 'strike')}{get_field(otm_pe, 'delta')}"
            )
    
    # -------------------------
    # Convenience methods
    # -------------------------
    def log_entry(self, token: str, symbol: str, strike: int, option_type: str,
                  side: str, quantity: int, price: float, phase: str, tag: str = ""):
        """Log entry trade"""
        self.log_trade(
            event_type="ENTRY",
            token=token,
            symbol=symbol,
            strike=strike,
            option_type=option_type,
            side=side,
            quantity=quantity,
            price=price,
            phase=phase,
            tag=tag
        )
    
    def log_exit(self, token: str, symbol: str, strike: int, option_type: str,
                 side: str, quantity: int, price: float, phase: str, 
                 reason: str, pnl: float, tag: str = ""):
        """Log exit trade"""
        self.log_trade(
            event_type="EXIT",
            token=token,
            symbol=symbol,
            strike=strike,
            option_type=option_type,
            side=side,
            quantity=quantity,
            price=price,
            phase=phase,
            reason=reason,
            pnl=pnl,
            tag=tag
        )
    
    def log_squareoff(self, token: str, symbol: str, strike: int, option_type: str,
                      side: str, quantity: int, price: float, phase: str, pnl: float):
        """Log squareoff trade"""
        self.log_trade(
            event_type="SQUAREOFF",
            token=token,
            symbol=symbol,
            strike=strike,
            option_type=option_type,
            side=side,
            quantity=quantity,
            price=price,
            phase=phase,
            reason="SQUAREOFF",
            pnl=pnl,
            tag="EOD"
        )
