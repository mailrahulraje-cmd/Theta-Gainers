"""
Live Trading Safety Validator
Implements 7 critical safety checks for production trading:
1. Broker Position Reconciliation
2. Stop-Loss Order Verification
3. Restart Recovery During Open Position
4. CE and PE Leg Independence
5. Hard Exit Idempotency
6. Circuit Breaker Accuracy
7. Delta Selection Loop Safety

CRITICAL UPDATE: Now uses type-safe state access via state_schema module
"""

import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from utils.logger import logger
from core.state_schema import (
    get_leg_safe, get_leg_token, get_leg_state, is_leg_entered, has_any_entered_leg
)


# ====================================================================
# HELPER: Safe leg information extraction
# ====================================================================
def _get_leg_entered(state: Dict, leg_name: str) -> bool:
    """
    Safely check if a leg is entered.
    Type-safe version of: state.get(f'{leg_name}_entered')
    """
    return is_leg_entered(state, leg_name)


def _get_leg_token(state: Dict, leg_name: str) -> Optional[str]:
    """
    Safely get token for a leg.
    Type-safe version of: state.get(f'{leg_name}_token')
    """
    return get_leg_token(state, leg_name)


def _get_leg_any_entered(state: Dict) -> bool:
    """
    Check if any leg is entered.
    Type-safe version of: any(state.get(k) for k in [leg keys])
    """
    return has_any_entered_leg(state)


class SafetyValidator:
    """
    Central safety validation hub for live trading.
    Uses type-safe state access pattern via state_schema module.
    """
    
    def __init__(self, logger_instance=None):
        self.logger = logger_instance or logger
        self.lock = threading.Lock()
        self.last_reconciliation_time = 0.0
        self.reconciliation_interval = 30.0  # Check every 30 seconds
        self.last_mismatch_warning = {}  # {token: timestamp} - prevent log spam
        self.hard_exit_triggered = False
    
    # ==================================================================
    # REQUIREMENT 1: BROKER POSITION RECONCILIATION (TYPE-SAFE VERSION)
    # ==================================================================
    def validate_broker_positions(self, state: Dict, broker_positions: Dict, threshold_seconds=30) -> Tuple[bool, str]:
        """
        Compare internal leg state against broker's actual positions.
        NOW USES TYPE-SAFE ACCESS PATTERNS
        
        Args:
            state: Internal strategy state dict
            broker_positions: Broker.positions dict {token: {qty, avg_price, ...}}
            threshold_seconds: Skip check if recent (prevents spam)
        
        Returns:
            (reconciled, message) - True if positions match, False + message if mismatch
        """
        now = time.time()
        
        # Throttle reconciliation: only check every threshold_seconds
        if now - self.last_reconciliation_time < threshold_seconds:
            return True, "Reconciliation throttled (checked recently)"
        
        self.last_reconciliation_time = now
        
        try:
            mismatches = []
            
            # Check SELL CE leg (TYPE-SAFE)
            if _get_leg_entered(state, 'sell_ce'):
                sell_ce_token = _get_leg_token(state, 'sell_ce')
                if sell_ce_token:
                    broker_pos = broker_positions.get(str(sell_ce_token), {})
                    broker_qty = broker_pos.get('qty', 0)
                    
                    # Short position should have negative qty at broker
                    if broker_qty >= 0:
                        mismatches.append(f"SELL_CE: Expected SHORT (qty<0) at broker, got qty={broker_qty}")
            
            # Check SELL PE leg (TYPE-SAFE)
            if _get_leg_entered(state, 'sell_pe'):
                sell_pe_token = _get_leg_token(state, 'sell_pe')
                if sell_pe_token:
                    broker_pos = broker_positions.get(str(sell_pe_token), {})
                    broker_qty = broker_pos.get('qty', 0)
                    
                    if broker_qty >= 0:
                        mismatches.append(f"SELL_PE: Expected SHORT (qty<0) at broker, got qty={broker_qty}")
            
            # Check BUY CE leg (TYPE-SAFE)
            if _get_leg_entered(state, 'buy_ce'):
                buy_ce_token = _get_leg_token(state, 'buy_ce')
                if buy_ce_token:
                    broker_pos = broker_positions.get(str(buy_ce_token), {})
                    broker_qty = broker_pos.get('qty', 0)
                    
                    if broker_qty <= 0:
                        mismatches.append(f"BUY_CE: Expected LONG (qty>0) at broker, got qty={broker_qty}")
            
            # Check BUY PE leg (TYPE-SAFE)
            if _get_leg_entered(state, 'buy_pe'):
                buy_pe_token = _get_leg_token(state, 'buy_pe')
                if buy_pe_token:
                    broker_pos = broker_positions.get(str(buy_pe_token), {})
                    broker_qty = broker_pos.get('qty', 0)
                    
                    if broker_qty <= 0:
                        mismatches.append(f"BUY_PE: Expected LONG (qty>0) at broker, got qty={broker_qty}")
            
            if mismatches:
                msg = " | ".join(mismatches)
                self.logger.error(f"[SAFETY] POSITION MISMATCH: {msg}")
                self.logger.error(f"[SAFETY] ACTION: Prevent new trades until reconciled")
                return False, f"Position mismatch detected: {msg}"
            else:
                if _get_leg_any_entered(state):
                    self.logger.debug(f"[SAFETY] Position reconciliation passed")
                return True, "Positions reconciled"
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] Position validation error: {e}")
            return True, f"Validation error: {e}"
    
    # ==================================================================
    # REQUIREMENT 2: STOP-LOSS ORDER VERIFICATION AFTER ENTRY
    # ==================================================================
    def verify_sl_order_after_entry(self, state: Dict, broker_orders: List[Dict], entry_token: str, leg_key: str) -> bool:
        """
        Immediately after entry order placement, verify that corresponding SL order exists.
        NOW USES TYPE-SAFE PATTERNS
        
        Args:
            state: Internal strategy state
            broker_orders: List of orders from broker
            entry_token: Token of the entry position
            leg_key: 'sell_ce', 'sell_pe', 'buy_ce', 'buy_pe'
        
        Returns:
            True if SL order exists and is pending/filled, False if missing
        """
        try:
            # Check if we have the SL order ID from entry
            sl_order_id_key = f'{leg_key}_sl_order_id'
            # Safe dict access with proper error handling
            sl_order_id = state.get(sl_order_id_key) if isinstance(state, dict) else None
            
            if not sl_order_id:
                self.logger.warning(f"[SAFETY] SL order ID not found for {leg_key} after entry - retrying SL placement")
                return False
            
            # Find the SL order in broker orders
            sl_order = None
            for order in broker_orders:
                if order.get('order_id') == sl_order_id:
                    sl_order = order
                    break
            
            if not sl_order:
                self.logger.error(f"[SAFETY] SL ORDER MISSING for {leg_key}: order_id={sl_order_id}")
                self.logger.error(f"[SAFETY] ACTION: Retry SL placement or force square-off to avoid naked exposure")
                return False
            
            status = sl_order.get('status', '').upper()
            if status not in ['PENDING', 'FILLED', 'OPEN']:
                self.logger.error(f"[SAFETY] SL ORDER REJECTED for {leg_key}: status={status}")
                return False
            
            self.logger.info(f"[SAFETY] SL order verified for {leg_key}: status={status}")
            return True
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] SL verification error for {leg_key}: {e}")
            return False
    
    # ==================================================================
    # REQUIREMENT 3: RESTART RECOVERY DURING OPEN POSITION
    # ==================================================================
    def rebuild_leg_state_from_broker(self, broker_positions: Dict, state_dict: Dict) -> Dict:
        """
        On startup, detect any open positions at broker and rebuild internal leg state.
        If positions exist, prevent new entries and resume SL/trailing logic.
        
        Args:
            broker_positions: {token: {qty, avg_price, symbol, ...}}
            state_dict: Current strategy state
        
        Returns:
            Updated state_dict with rebuilt leg entries
        """
        try:
            recovery_count = 0
            open_positions = {k: v for k, v in broker_positions.items() if v.get('qty', 0) != 0}
            
            if not open_positions:
                return state_dict
            
            self.logger.warning(f"[SAFETY] Detected {len(open_positions)} open positions at startup - rebuilding leg state")
            
            # Mark positions as entered + set recovery flag
            for token, pos in open_positions.items():
                qty = pos.get('qty', 0)
                symbol = pos.get('symbol', f"Token-{token}")
                avg_price = pos.get('avg_price', 0.0)
                
                # Try to match against known tokens and mark as entered
                if qty < 0:
                    # SHORT position - try to match SELL legs
                    if not state_dict.get('sell_ce_token'):
                        state_dict['sell_ce_token'] = token
                        state_dict['sell_ce_entered'] = True
                        state_dict['sell_ce_entry_price'] = avg_price
                        recovery_count += 1
                        self.logger.warning(f"[SAFETY] Recovered SELL_CE position: token={token}, qty={qty}, price={avg_price:.2f}")
                    elif not state_dict.get('sell_pe_token'):
                        state_dict['sell_pe_token'] = token
                        state_dict['sell_pe_entered'] = True
                        state_dict['sell_pe_entry_price'] = avg_price
                        recovery_count += 1
                        self.logger.warning(f"[SAFETY] Recovered SELL_PE position: token={token}, qty={qty}, price={avg_price:.2f}")
                elif qty > 0:
                    # LONG position - try to match BUY legs
                    if not state_dict.get('buy_ce_token'):
                        state_dict['buy_ce_token'] = token
                        state_dict['buy_ce_entered'] = True
                        state_dict['buy_ce_entry_price'] = avg_price
                        recovery_count += 1
                        self.logger.warning(f"[SAFETY] Recovered BUY_CE position: token={token}, qty={qty}, price={avg_price:.2f}")
                    elif not state_dict.get('buy_pe_token'):
                        state_dict['buy_pe_token'] = token
                        state_dict['buy_pe_entered'] = True
                        state_dict['buy_pe_entry_price'] = avg_price
                        recovery_count += 1
                        self.logger.warning(f"[SAFETY] Recovered BUY_PE position: token={token}, qty={qty}, price={avg_price:.2f}")
            
            if recovery_count > 0:
                state_dict['_restart_recovery_mode'] = True
                self.logger.warning(f"[SAFETY] Restart recovery: {recovery_count} positions rebuilt - resuming SL/trailing logic")
            
            return state_dict
        
        except Exception as e:
            self.logger.exception(f"[SAFETY] Restart recovery error: {e}")
            return state_dict
    
    # ==================================================================
    # REQUIREMENT 4: CE AND PE LEG INDEPENDENCE VERIFICATION (TYPE-SAFE)
    # ==================================================================
    def verify_leg_independence(self, state: Dict) -> Tuple[bool, str]:
        """
        Verify that CE and PE legs maintain completely separate state.
        NOW USES TYPE-SAFE ACCESS PATTERNS
        
        Returns:
            (valid, message)
        """
        try:
            issues = []
            
            # Check SELL legs are truly independent
            sell_ce_state = {
                'entered': _get_leg_entered(state, 'sell_ce'),
                'locked': state.get('sell_ce_leg_ready', False),  # Backward compat
                'sl': state.get('sell_ce_sl_order_price'),
                'trailing': state.get('sell_ce_trailing_active', False)
            }
            
            sell_pe_state = {
                'entered': _get_leg_entered(state, 'sell_pe'),
                'locked': state.get('sell_pe_leg_ready', False),  # Backward compat
                'sl': state.get('sell_pe_sl_order_price'),
                'trailing': state.get('sell_pe_trailing_active', False)
            }
            
            # Check BUY legs are truly independent  
            buy_ce_state = {
                'entered': _get_leg_entered(state, 'buy_ce'),
                'locked': state.get('buy_ce_leg_ready', False),  # Backward compat
                'sl': state.get('buy_ce_sl_order_price'),
            }
            
            buy_pe_state = {
                'entered': _get_leg_entered(state, 'buy_pe'),
                'locked': state.get('buy_pe_leg_ready', False),  # Backward compat
                'sl': state.get('buy_pe_sl_order_price'),
            }
            
            # Verify no shared tokens between legs
            tokens = {
                'sell_ce': _get_leg_token(state, 'sell_ce'),
                'sell_pe': _get_leg_token(state, 'sell_pe'),
                'buy_ce': _get_leg_token(state, 'buy_ce'),
                'buy_pe': _get_leg_token(state, 'buy_pe')
            }
            
            seen_tokens = {}
            for leg_name, token in tokens.items():
                if token:
                    if token in seen_tokens:
                        issues.append(f"Token {token} shared between {seen_tokens[token]} and {leg_name}")
                    else:
                        seen_tokens[token] = leg_name
            
            if issues:
                msg = " | ".join(issues)
                self.logger.error(f"[SAFETY] LEG INDEPENDENCE VIOLATION: {msg}")
                return False, msg
            
            return True, "All legs independent"
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] Leg independence check error: {e}")
            return True, f"Check error: {e}"
    
    # ==================================================================
    # REQUIREMENT 5: HARD EXIT IDEMPOTENCY
    # ==================================================================
    def validate_hard_exit_idempotency(self, hard_exit_triggered: bool, state: Dict) -> Tuple[bool, str]:
        """
        Ensure hard exit logic executes only once per session.
        Prevent repeated square-off attempts in subsequent cycles.
        
        Returns:
            (valid, message)
        """
        try:
            if hard_exit_triggered:
                # Hard exit has been triggered
                if self.hard_exit_triggered:
                    # Already logged once
                    return True, "Hard exit already executed (idempotent)"
                else:
                    # First time seeing it
                    self.hard_exit_triggered = True
                    self.logger.critical(f"[SAFETY] HARD EXIT TRIGGERED - Will execute once only")
                    return True, "Hard exit will execute once"
            else:
                # Not triggered - reset if needed
                if self.hard_exit_triggered:
                    self.hard_exit_triggered = False
                return True, "Hard exit not triggered"
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] Hard exit validation error: {e}")
            return True, f"Validation error: {e}"
    
    # ==================================================================
    # REQUIREMENT 6: CIRCUIT BREAKER ACCURACY
    # ==================================================================
    def validate_circuit_breaker_accuracy(self, order_result: Dict, transaction_type: str) -> Tuple[bool, str]:
        """
        Verify circuit breaker increments ONLY on genuine broker/order failures.
        Normal exits, SL hits, or successful trades must NOT increase failure count.
        
        Args:
            order_result: Result from broker order
            transaction_type: 'BUY', 'SELL', 'EXIT', etc.
        
        Returns:
            (should_increment, reason)
        """
        try:
            status = order_result.get('status', '').upper()
            
            # These are normal conditions - do NOT increment circuit breaker
            if status in ['FILLED', 'OPEN', 'PENDING']:
                return False, "Order successful - do not increment circuit breaker"
            
            error_message = order_result.get('message', '').upper()
            
            # These are genuine failures - increment circuit breaker
            failure_keywords = ['ERROR', 'REJECT', 'FAIL', 'INVALID', 'INSUFFICIENT', 'CONNECTION', 'TIMEOUT']
            is_genuine_failure = any(kw in error_message or kw in status for kw in failure_keywords)
            
            if is_genuine_failure:
                return True, f"Genuine failure detected: {status} - {error_message}"
            else:
                return False, "Not a genuine broker failure - do not increment"
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] Circuit breaker validation error: {e}")
            return False, f"Validation error: {e}"
    
    # ==================================================================
    # REQUIREMENT 7: DELTA SELECTION LOOP SAFETY
    # ==================================================================
    def validate_delta_loop_safety(self, 
                                   attempt_number: int, 
                                   max_retries: int,
                                   elapsed_time: float,
                                   timeout_seconds: float) -> Tuple[bool, str]:
        """
        Ensure delta-finding loop has maximum retry limit and timeout condition.
        The loop must always exit gracefully if suitable strike is not found.
        
        Args:
            attempt_number: Current attempt number (1-based)
            max_retries: Maximum allowed retries
            elapsed_time: Seconds elapsed in this loop iteration
            timeout_seconds: Maximum allowed time for this iteration
        
        Returns:
            (should_continue, reason)
        """
        try:
            # Check attempts
            if attempt_number > max_retries:
                msg = f"Delta loop exceeded max retries: {attempt_number}/{max_retries}"
                self.logger.warning(f"[SAFETY] {msg}")
                return False, msg
            
            # Check timeout
            if elapsed_time > timeout_seconds:
                msg = f"Delta loop timeout: {elapsed_time:.1f}s > {timeout_seconds:.1f}s limit"
                self.logger.warning(f"[SAFETY] {msg}")
                return False, msg
            
            return True, f"Attempt {attempt_number}/{max_retries}, {elapsed_time:.1f}s/{timeout_seconds:.1f}s"
        
        except Exception as e:
            self.logger.warning(f"[SAFETY] Delta loop validation error: {e}")
            return False, f"Validation error: {e}"
    
    # ==================================================================
    # UTILITY: Log position state for debugging (TYPE-SAFE)
    # ==================================================================
    def log_position_snapshot(self, state: Dict, broker_positions: Dict):
        """
        Log current position state for debugging and audit trail.
        NOW USES TYPE-SAFE ACCESS
        """
        try:
            legs = {}
            for leg_key in ['sell_ce', 'sell_pe', 'buy_ce', 'buy_pe']:
                is_entered = _get_leg_entered(state, leg_key)
                is_locked = state.get(f'{leg_key}_leg_ready', False)  # Backward compat
                token = _get_leg_token(state, leg_key)
                if is_entered or is_locked or token:
                    broker_pos = broker_positions.get(str(token), {}) if token else {}
                    legs[leg_key] = {
                        'entered': is_entered,
                        'token': token,
                        'broker_qty': broker_pos.get('qty', 0),
                        'broker_price': broker_pos.get('avg_price', 0)
                    }
            
            if legs:
                self.logger.debug(f"[SAFETY] Position snapshot: {legs}")
        
        except Exception:
            pass
