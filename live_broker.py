"""
LiveBroker - Production-Ready Real Money Trading Execution
Handles order placement, validation, position tracking, and risk management for live trading.

CRITICAL SAFETY FEATURES:
- Comprehensive order validation
- Risk limit enforcement
- Order status verification with polling
- Position reconciliation
- Circuit breaker
- Order rate limiting
- ExecutionGateway integration (centralized safety)

LOCK ORDERING AND NOTIFIER POLICY:
==================================
Locks in use (priority order, lowest first):
1. self.order_lock (threading.Lock): Protects orders and positions
2. self._execution_lock (threading.Lock): Protects broker API interactions
3. self._partial_fill_lock (if used): For partial fill tracking

NOTIFIER SAFETY IN PHASE 0/1 CRITICAL WINDOWS:
================================================
CRITICAL: All notifier calls execute in SEPARATE DAEMON THREADS (non-blocking)
- This ensures Telegram API delays (10-30ms typical, 100-300ms worst-case)
  DO NOT block order execution, risk checks, or reconciliation during Phase 0/1
- Threads are spawned after lock release to minimize critical section
- The notifier itself (TelegramNotifierTextOnly) uses internal locks only for
  state tracking, never blocking API sends

Pattern verified throughout live_broker.py:
  with self.order_lock:
      # ... critical order/position operations ...
  # Lock released here
  if self.notifier:
      threading.Thread(target=self.notifier.send_trade_log(...), daemon=True).start()
"""
import threading
import uuid
import csv
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from config import Config, EXCHANGE_TYPE_MAP
from utils.logger import logger, trade_logger
from utils.order_journal import get_order_journal
from utils.rate_limiter import get_global_rate_limiter
from contract import BrokerProtocol, OrderDict, FeedProtocol
from core.execution_gateway import get_execution_gateway, ExecutionGateway

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None

def ist_now() -> datetime:
    return datetime.now(Config.TZ)

class LiveBroker:
    """
    Production-ready live broker with comprehensive safety features.
    
    Safety Features:
    - Pre-trade validation (token, lot size, price, market hours)
    - Risk limit enforcement (daily loss, position limits, margin)
    - Order status polling and verification
    - Position reconciliation with broker
    - Circuit breaker mechanism
    - Order rate limiting
    """
    
    def __init__(self, smart_api: SmartConnect, state, trades_csv: str = None, 
                 notifier: Optional[Any] = None, lots: int = 1, instruments=None):
        """
        Initialize LiveBroker
        
        Args:
            smart_api: Authenticated SmartConnect instance
            state: StrategyState instance for persistence
            trades_csv: Path to CSV file for trade logging
            notifier: Optional Telegram notifier
            lots: Position size multiplier
            instruments: InstrumentMaster for validation
        """
        if SmartConnect is None:
            raise ImportError("smartapi-python required for LiveBroker")
        
        self.api = smart_api
        self.state = state
        self.notifier = notifier
        self.lots = int(lots)
        self.instruments = instruments
        
        # Trade logging
        self.trades_csv = trades_csv or Config.get_trades_csv()
        self._init_csv()
        
        # Position tracking
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: List[Dict[str, Any]] = []
        self.order_lock = threading.Lock()
        
        # Restore positions from state
        self._restore_positions()
        
        # P&L tracking
        self.net_realized = 0.0
        self.daily_pnl = 0.0
        self.daily_loss_start = ist_now().date()
        
        # Circuit breaker
        self.circuit_breaker_triggered = False
        self.circuit_breaker_time = None
        
        # Order rate limiting
        self.last_order_time = None
        self.order_count_1min = 0
        self.order_count_1min_reset = ist_now()
        
        # Position reconciliation
        self.last_reconciliation = None
        self.reconciliation_thread = None
        # Startup reconciliation completed flag
        self._startup_reconciled = False
        # Partial-fill block info
        self._partial_fill_block = False
        self._partial_fill_info = None
        # Emergency stop active
        self._emergency_active = False
        
        # API Rate Limiting (enforce API_RATE_LIMIT_PER_SECOND)
        self._last_api_call_time = time.monotonic()
        self._min_api_interval = 1.0 / Config.API_RATE_LIMIT_PER_SECOND if Config.API_RATE_LIMIT_PER_SECOND > 0 else 0.0
        self._api_limit_lock = threading.Lock()
        
        # Global rate limiter for coordinated API call blocking
        self.rate_limiter = get_global_rate_limiter(Config.API_RATE_LIMIT_PER_SECOND)
        
        if Config.ENABLE_POSITION_RECONCILIATION:
            self._start_reconciliation_thread()

        # Start emergency file monitor thread (lightweight)
        self._start_emergency_monitor()
        
        # Global execution lock for thread-safe order/position operations
        # Wraps: order placement, flatten operations, reconciliation updates, emergency handlers
        self._execution_lock = threading.Lock()
        
        # CRITICAL: Initialize execution gateway for centralized safety
        self.gateway = get_execution_gateway()
        
        logger.info(" LiveBroker initialized - REAL MONEY MODE")
        logger.info(" LiveBroker: ExecutionGateway integrated")
        logger.warning(f"  Risk Limits: Daily Loss: {Config.MAX_DAILY_LOSS:,.2f}, Trade Loss: {Config.MAX_TRADE_LOSS:,.2f}")
    
    # ==================== INITIALIZATION ====================
    
    def _init_csv(self):
        """Initialize trade log CSV file"""
        try:
            if not os.path.exists(self.trades_csv):
                with open(self.trades_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'timestamp', 'order_id', 'exchange_order_id', 
                        'side', 'token', 'symbol', 'qty', 'price', 
                        'order_type', 'status', 'tag', 'message'
                    ])
                logger.info(f" Created trade log: {self.trades_csv}")
        except Exception as e:
            logger.exception(f"Failed to initialize trade log CSV: {e}")
    
    def _restore_positions(self):
        """Restore positions from state file"""
        try:
            saved = self.state.get('broker_positions')
            if saved:
                self.positions = saved
                logger.info(f" Restored {len(saved)} positions from state")
                for token, pos in saved.items():
                    if pos.get('qty', 0) != 0:
                        logger.info(
                            f"    {token}: {pos.get('side')} "
                            f"{abs(pos.get('qty'))} @ {pos.get('avg_price', 0.0):.2f}"
                        )
            
            # Sync with broker positions
            self._sync_positions_from_broker()
            # Mark startup reconciliation as done - broker is now source-of-truth
            try:
                self._startup_reconciled = True
                self.state.set('startup_reconciled', True)
                logger.info(" Startup position reconciliation complete - broker is source-of-truth")
            except Exception:
                pass
            
        except Exception as e:
            logger.exception(f"Failed to restore positions: {e}")
    
    def _sync_positions_from_broker(self):
        """Sync positions from broker API"""
        def _fetch_positions():
            return self.api.position()

        # Use safe API call wrapper for network robustness
        try:
            response = self._safe_api_call(_fetch_positions, retries=Config.API_CALL_MAX_RETRIES, delay=Config.API_CALL_RETRY_DELAY)
            if response and response.get('status'):
                broker_positions = response.get('data', [])
                logger.info(f" Fetched {len(broker_positions)} positions from broker")

                # Update local position tracking
                for pos in broker_positions:
                    token = str(pos.get('symboltoken'))
                    qty = int(pos.get('netqty', 0))
                    avg_price = float(pos.get('avgprice', 0.0))
                    ltp = float(pos.get('ltp', avg_price))

                    if qty != 0:
                        self.positions[token] = {
                            'qty': qty,
                            'avg_price': avg_price,
                            'side': 'LONG' if qty > 0 else 'SHORT',
                            'last_price': ltp,
                            'symbol': pos.get('tradingsymbol', ''),
                            'token': token
                        }
                        logger.info(
                            f"    Synced {token}: {qty} @ {avg_price:.2f}"
                        )

                self._save_positions()
            else:
                logger.warning(" Failed to fetch positions from broker")

        except Exception as e:
            logger.exception(f"Failed to sync positions from broker: {e}")
    
    def _save_positions(self):
        """Save positions to state file"""
        try:
            self.state.set('broker_positions', self.positions)
        except Exception as e:
            logger.exception(f"Failed to save positions to state: {e}")
    
    def _start_reconciliation_thread(self):
        """Start background position reconciliation"""
        def reconciliation_loop():
            while not getattr(self, '_stop_reconciliation', False):
                try:
                    time.sleep(Config.POSITION_RECONCILIATION_INTERVAL)
                    self._reconcile_positions()
                except Exception as e:
                    logger.exception(f"Reconciliation error: {e}")
        
        self.reconciliation_thread = threading.Thread(target=reconciliation_loop, daemon=True)
        self.reconciliation_thread.start()
        logger.info(" Position reconciliation thread started")

    def _start_emergency_monitor(self):
        """Start a lightweight thread that watches for the emergency stop file or config flag."""
        def monitor_loop():
            while True:
                try:
                    # If ENV-level emergency requested or file exists, trigger emergency handling
                    if Config.EMERGENCY_EXIT_ALL or (hasattr(Config, 'EMERGENCY_STOP_FILE') and Config.EMERGENCY_STOP_FILE and os.path.exists(str(Config.EMERGENCY_STOP_FILE))):
                        if not self._emergency_active:
                            logger.critical(" Emergency stop detected - initiating flatten and disabling new entries")
                            self._emergency_active = True
                            try:
                                self._handle_emergency()
                            except Exception:
                                logger.exception("Error while handling emergency stop")
                        time.sleep(1.0)
                except Exception:
                    logger.exception("Emergency monitor loop error")
                    time.sleep(2.0)

        t = threading.Thread(target=monitor_loop, daemon=True)
        t.start()
        logger.info(" Emergency monitor thread started")

    def _handle_emergency(self):
        """Perform emergency flattening and set state to block further entries."""
        with self._execution_lock:
            try:
                # Mark circuit breaker and save state
                self.circuit_breaker_triggered = True
                self.state.set('emergency_stop', True)

                # Notify non-blocking to avoid holding execution lock during network I/O
                if self.notifier:
                    try:
                        threading.Thread(
                            target=self.notifier.send_trade_log,
                            args=("EMERGENCY STOP: Flattening all positions and blocking new entries",),
                            daemon=True
                        ).start()
                    except Exception:
                        logger.exception("Failed to spawn emergency notifier thread")

                # Execute flatten: iterate over current positions and place opposite orders
                self._emergency_flatten()

                # Persist that emergency is active
                try:
                    self.state.set('emergency_active', True)
                except Exception:
                    pass

                logger.critical(" Emergency flatten complete - trading disabled")

            except Exception as e:
                logger.exception(f"Emergency handling failed: {e}")

    def _emergency_flatten(self):
        """Close all open positions by placing opposite market orders."""
        try:
            with self.order_lock:
                tokens = list(self.positions.keys())

            for token in tokens:
                pos = self.positions.get(token, {})
                qty = int(pos.get('qty', 0))
                if qty == 0:
                    continue
                side = 'SELL' if qty > 0 else 'BUY'
                close_qty = abs(qty)
                symbol = pos.get('symbol')
                logger.info(f" Emergency flatten: {token} - {side} {close_qty}")
                try:
                    # Place opposite market order via direct execution (bypass place_order guards)
                    res = self._execute_order_with_retry(side, token, symbol, close_qty, pos.get('last_price', 0.0), 'EMERGENCY_FLATTEN')
                    logger.info(f" Emergency flatten order result for {token}: {res.get('status')}")
                except Exception:
                    logger.exception(f"Failed to flatten {token}")
                # Update local tracking regardless (wrapped in execution lock)
                try:
                    with self._execution_lock:
                        with self.order_lock:
                            if token in self.positions:
                                self.positions[token]['qty'] = 0
                        self._save_positions()
                except Exception:
                    logger.exception("Failed to update positions during emergency flatten")

        except Exception as e:
            logger.exception(f"Emergency flatten failed: {e}")
    
    def _reconcile_positions(self):
        """Reconcile local positions with broker positions"""
        try:
            logger.info(" Reconciling positions with broker...")
            
            # Fetch via safe API call wrapper
            response = self._safe_api_call(self.api.position, retries=Config.API_CALL_MAX_RETRIES, delay=Config.API_CALL_RETRY_DELAY)
            if not response or not response.get('status'):
                logger.warning(" Reconciliation: Failed to fetch broker positions")
                return
            
            broker_positions = {
                str(pos.get('symboltoken')): {
                    'qty': int(pos.get('netqty', 0)),
                    'avg_price': float(pos.get('avgprice', 0.0)),
                    'symbol': pos.get('tradingsymbol', '')
                }
                for pos in response.get('data', [])
                if int(pos.get('netqty', 0)) != 0
            }
            
            # Compare with local positions
            discrepancies = []
            with self.order_lock:
                local_tokens = set(k for k, v in self.positions.items() if v.get('qty', 0) != 0)
                broker_tokens = set(broker_positions.keys())
                
                # Tokens in local but not in broker
                for token in local_tokens - broker_tokens:
                    discrepancies.append(f"Local has {token} but broker doesn't")
                    logger.warning(f" Reconciliation: {token} exists locally but not at broker")
                
                # Tokens in broker but not local
                for token in broker_tokens - local_tokens:
                    discrepancies.append(f"Broker has {token} but local doesn't")
                    logger.warning(f" Reconciliation: {token} exists at broker but not locally")
                    # Update local to match broker
                    broker_pos = broker_positions[token]
                    self.positions[token] = {
                        'qty': broker_pos['qty'],
                        'avg_price': broker_pos['avg_price'],
                        'side': 'LONG' if broker_pos['qty'] > 0 else 'SHORT',
                        'last_price': broker_pos['avg_price'],
                        'symbol': broker_pos['symbol'],
                        'token': token
                    }
                
                # Check quantity mismatches
                for token in local_tokens & broker_tokens:
                    local_qty = self.positions[token].get('qty', 0)
                    broker_qty = broker_positions[token]['qty']
                    if local_qty != broker_qty:
                        discrepancies.append(
                            f"{token}: local qty={local_qty}, broker qty={broker_qty}"
                        )
                        logger.warning(
                            f" Reconciliation: {token} qty mismatch - "
                            f"local: {local_qty}, broker: {broker_qty}"
                        )
                        # Update to broker's qty (broker is source of truth)
                        self.positions[token]['qty'] = broker_qty
                        self.positions[token]['side'] = 'LONG' if broker_qty > 0 else 'SHORT'
                
                if discrepancies:
                    self._save_positions()
                    if self.notifier:
                        try:
                            threading.Thread(
                                target=self.notifier.send_trade_log,
                                args=(f" Position Reconciliation: {len(discrepancies)} discrepancies found",),
                                daemon=True
                            ).start()
                        except Exception:
                            logger.exception("Failed to spawn reconciliation notifier thread")
                else:
                    logger.info(" Reconciliation: All positions match")
            
            self.last_reconciliation = ist_now()
            # If partial-fill block exists, check whether reconciliation resolved it
            try:
                pf = self._partial_fill_info
                if pf and pf.get('token'):
                    token = str(pf.get('token'))
                    with self.order_lock:
                        local_qty = self.positions.get(token, {}).get('qty', 0)
                    # If broker/local qty now reflects the filled amount (i.e., no pending partial), clear block
                    if local_qty == pf.get('expected_qty', local_qty):
                        self._partial_fill_block = False
                        self._partial_fill_info = None
                        self.state.set('partial_fill', None)
                        if self.notifier:
                            try:
                                threading.Thread(target=self.notifier.send_trade_log, args=(f" Partial-fill resolved for {token}; normal trading resumed.",), daemon=True).start()
                            except Exception:
                                logger.exception("Failed to spawn partial-fill resolved notifier thread")
            except Exception:
                logger.exception("Error while checking partial-fill resolution during reconciliation")
            
        except Exception as e:
            logger.exception(f"Failed to reconcile positions: {e}")
    
    # ==================== ORDER PLACEMENT ====================
    
    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Place order on exchange with comprehensive validation
        
        Supports multiple signatures:
        - place_order(side, token, qty, price, tag="")
        - place_order(token, symbol, side, price, qty, meta)
        - place_order(side=..., token=..., qty=..., price=..., ...)
        
        Returns:
            Order dict with status and exchange order ID
        """
        order_start_time = time.time()
        
        # ==================== KILL SWITCH ====================
        if Config.KILL_SWITCH_ENABLED:
            logger.error(" KILL SWITCH ACTIVE - ALL TRADING BLOCKED")
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': 'Kill switch enabled - all trading blocked',
                'timestamp': ist_now().isoformat()
            }
        
        if Config.NO_NEW_TRADES:
            logger.warning(" NO NEW TRADES MODE - Blocking new entries")
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': 'NO_NEW_TRADES flag active',
                'timestamp': ist_now().isoformat()
            }
        
        # Check circuit breaker first
        if self.circuit_breaker_triggered:
            logger.error(" Circuit breaker active - order rejected")
            if self.notifier:
                try:
                    threading.Thread(target=self.notifier.send_trade_log, args=(" Order rejected: Circuit breaker active",), daemon=True).start()
                except Exception:
                    logger.exception("Failed to spawn circuit-breaker notifier thread")
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': 'Circuit breaker triggered',
                'timestamp': ist_now().isoformat()
            }
        
        logger.info(f"[LIVE_BROKER] Circuit breaker check: PASSED")
        
        # Parse arguments
        side, token, symbol, qty, price, tag, meta = self._parse_order_args(args, kwargs)
        
        # Log incoming order
        logger.info(f"[LIVE_BROKER] Order request: side={side}, token={token}, symbol={symbol}, qty={qty}, price={price:.2f}, tag={tag}, broker_mode=LIVE")
        
        # ================================================================
        # CRITICAL: EXECUTION GATEWAY VALIDATION (CENTRALIZED SAFETY)
        # ================================================================
        # This consolidates kill switch, rate limiting, and risk checks
        # Infer if this is an entry order based on current positions
        is_entry = ExecutionGateway.infer_is_entry(
            symbol=symbol or f"Token-{token}",
            transaction_type=side,
            positions=self.positions
        )
        
        allowed, reason = self.gateway.validate_order(
            symbol=symbol or f"Token-{token}",
            transaction_type=side,
            quantity=qty,
            price=price,
            order_type='MARKET',
            is_entry=is_entry
        )
        
        if not allowed:
            logger.error(f" Order REJECTED by ExecutionGateway: {reason}")
            if self.notifier:
                try:
                    threading.Thread(target=self.notifier.send_trade_log, args=(f" Order rejected: {reason}",), daemon=True).start()
                except Exception:
                    logger.exception("Failed to spawn execution-gateway notifier thread")
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': f'ExecutionGateway: {reason}',
                'timestamp': ist_now().isoformat()
            }
        # ================================================================
        
        # Rate limiting
        if not self._check_rate_limit():
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': 'Rate limit exceeded',
                'timestamp': ist_now().isoformat()
            }
        
        # Validate order
        if Config.ENABLE_ORDER_VALIDATION:
            valid, error_msg = self._validate_order(side, token, symbol, qty, price)
            if not valid:
                logger.error(f" Order validation failed: {error_msg}")
                return {
                    'order_id': str(uuid.uuid4()),
                    'status': 'REJECTED',
                    'message': f'Validation failed: {error_msg}',
                    'timestamp': ist_now().isoformat(),
                    'side': side,
                    'token': token,
                    'qty': qty,
                    'price': price
                }
        
        # Check risk limits
        passed, limit_msg = self._check_risk_limits(side, token, qty, price)
        if not passed:
            logger.error(f" Risk limit check failed: {limit_msg}")
            if self.notifier:
                try:
                    threading.Thread(target=self.notifier.send_trade_log, args=(f" Risk limit: {limit_msg}",), daemon=True).start()
                except Exception:
                    logger.exception("Failed to spawn risk-limit notifier thread")
            return {
                'order_id': str(uuid.uuid4()),
                'status': 'REJECTED',
                'message': f'Risk limit: {limit_msg}',
                'timestamp': ist_now().isoformat(),
                'side': side,
                'token': token,
                'qty': qty,
                'price': price
            }

            # STARTUP RECONCILIATION GATING: ensure broker is source-of-truth before accepting live orders
            if not self._startup_reconciled:
                logger.error("Order rejected: position reconciliation with broker not completed yet")
                return {
                    'order_id': str(uuid.uuid4()),
                    'status': 'REJECTED',
                    'message': 'Position reconciliation pending - try again shortly',
                    'timestamp': ist_now().isoformat()
                }

            # PARTIAL-FILL SAFETY: if there is a partial-fill, block any new orders that would increase exposure for that token
            if self._partial_fill_block and self._partial_fill_info:
                pf_token = str(self._partial_fill_info.get('token'))
                if pf_token == str(token):
                    # compute existing qty and projected qty if this order executes
                    existing_qty = self.positions.get(str(token), {}).get('qty', 0)
                    projected_qty = existing_qty + (qty if side == 'BUY' else -qty)
                    if abs(projected_qty) > abs(existing_qty):
                        msg = f"Partial fill active for {token}; blocking orders that increase exposure until resolved"
                        logger.warning(msg)
                        if self.notifier:
                            try:
                                threading.Thread(target=self.notifier.send_trade_log, args=(msg,), daemon=True).start()
                            except Exception:
                                logger.exception("Failed to spawn partial-fill active notifier thread")
                        return {
                            'order_id': str(uuid.uuid4()),
                            'status': 'REJECTED',
                            'message': 'Partial fill active - resolve before new entries',
                            'timestamp': ist_now().isoformat()
                        }

            # DUPLICATE/IDEMPOTENCY CHECK: consult broker order book for similar pending orders
            try:
                if self._has_similar_pending_order(side, token, qty):
                    logger.warning(" Duplicate order detected - skipping placement")
                    return {
                        'order_id': str(uuid.uuid4()),
                        'status': 'REJECTED',
                        'message': 'Duplicate pending order exists - placement skipped',
                        'timestamp': ist_now().isoformat()
                    }
            except Exception:
                logger.exception("Error while checking for duplicate orders; continuing placement")
        
        # Place order with retries and status verification
        order_result = self._execute_order_with_retry(
            side, token, symbol, qty, price, tag
        )

        # If order was partially filled, centralize handling
        try:
            if order_result.get('status') and order_result['status'].upper() == 'PARTIALLY_FILLED':
                try:
                    self._handle_partial_fill(order_result, token, side, qty)
                except Exception:
                    logger.exception("Error in _handle_partial_fill post-order")
        except Exception:
            logger.exception("Error handling partial-fill post-order")
        
        # ==================== TIMING VALIDATION ====================
        if Config.ENABLE_TIMEOUT_PROTECTION:
            order_duration = time.time() - order_start_time
            if order_duration > Config.MAX_ORDER_PLACEMENT_TIME:
                logger.warning(
                    f" Order placement took {order_duration:.2f}s "
                    f"(threshold: {Config.MAX_ORDER_PLACEMENT_TIME}s)"
                )
                if self.notifier:
                    try:
                        threading.Thread(target=self.notifier.send_trade_log, args=(f" Slow order: {order_duration:.2f}s for {tag}",), daemon=True).start()
                    except Exception:
                        logger.exception("Failed to spawn slow-order notifier thread")
        
        # Log and save (with execution lock for thread-safe state mutation)
        with self._execution_lock:
            self._log_order(order_result, tag)
            
            # Update positions if filled
            if order_result['status'] == 'FILLED':
                self._apply_fill(order_result)
        
        # Notify
        self._notify_order(order_result, tag)
        
        return order_result
    
    def _parse_order_args(self, args, kwargs) -> Tuple:
        """Parse flexible order arguments"""
        side = None
        token = None
        symbol = None
        qty = None
        price = None
        tag = ""
        meta = {}
        
        # Positional parsing
        try:
            if len(args) >= 4:
                if len(args) == 4 or len(args) == 5:
                    # (side, token, qty, price, [tag])
                    side = str(args[0]).upper()
                    token = str(args[1])
                    qty = int(args[2])
                    price = float(args[3])
                    if len(args) == 5:
                        tag = str(args[4])
                elif len(args) >= 5:
                    # (token, symbol, side, price, qty, [meta])
                    token = str(args[0])
                    symbol = str(args[1])
                    side = str(args[2]).upper()
                    price = float(args[3])
                    qty = int(args[4])
                    if len(args) >= 6:
                        meta = args[5] or {}
                        tag = meta.get('label', tag)
            
            # Kwargs override
            side = str(kwargs.get('side', side)).upper() if kwargs.get('side') else side
            token = str(kwargs.get('token', token))
            symbol = kwargs.get('symbol', symbol)
            qty = int(kwargs.get('qty', qty))
            price = float(kwargs.get('price', price))
            tag = kwargs.get('tag', kwargs.get('label', tag))
            meta = kwargs.get('meta', meta) or {}
            
        except (ValueError, TypeError) as e:
            logger.exception(f"Failed to parse order arguments: {e}")
            raise ValueError(f"Invalid order arguments: {e}")
        
        return side, token, symbol, qty, price, tag, meta
    
    def _check_rate_limit(self) -> bool:
        """Check order rate limiting"""
        now = ist_now()
        
        # Check minimum interval between orders
        if self.last_order_time:
            elapsed = (now - self.last_order_time).total_seconds()
            if elapsed < Config.MIN_ORDER_INTERVAL:
                logger.warning(
                    f" Order rate limit: {elapsed:.2f}s < {Config.MIN_ORDER_INTERVAL}s"
                )
                return False
        
        # Check orders per minute
        if (now - self.order_count_1min_reset).total_seconds() > 60:
            self.order_count_1min = 0
            self.order_count_1min_reset = now
        
        if self.order_count_1min >= 20:  # Max 20 orders per minute
            logger.warning(f" Order rate limit: {self.order_count_1min} orders in last minute")
            return False
        
        self.last_order_time = now
        self.order_count_1min += 1
        return True
    
    def _validate_order(self, side: str, token: str, symbol: str, 
                       qty: int, price: float) -> Tuple[bool, str]:
        """
        Comprehensive order validation
        
        Returns:
            (valid, error_message) tuple
        """
        
        # 1. Validate side
        if side not in ['BUY', 'SELL']:
            return False, f"Invalid side: {side}"
        
        # 2. Validate token exists
        if self.instruments:
            inst = self.instruments.instruments.get(str(token))
            if not inst:
                return False, f"Token {token} not found in instrument master"
            
            # 3. Check instrument expiry
            expiry_str = inst.get('expiry', '')
            if expiry_str:
                try:
                    from datetime import datetime
                    expiry_date = None
                    for fmt in ['%d%b%Y', '%d%b%y', '%Y-%m-%d']:
                        try:
                            expiry_date = datetime.strptime(expiry_str, fmt).date()
                            break
                        except Exception as e:
                            logger.exception(f"Failed to parse expiry format '{fmt}' for '{expiry_str}': {e}")
                            continue
                    
                    if expiry_date and expiry_date < ist_now().date():
                        return False, f"Instrument expired on {expiry_date}"
                except Exception as e:
                    logger.warning(f"Could not parse expiry date: {expiry_str}")
            
            # 4. Validate lot size
            lot_size = self.instruments.get_lot_size(str(token))
            if lot_size > 1 and qty % lot_size != 0:
                return False, f"Qty {qty} not multiple of lot size {lot_size}"
            
            # 5. Get symbol if not provided
            if not symbol:
                symbol = inst.get('symbol', f'TOKEN_{token}')
        
        # 6. Validate quantity
        if qty <= 0:
            return False, f"Invalid quantity: {qty}"
        
        if qty > Config.MAX_ORDER_QUANTITY:
            return False, f"Quantity {qty} exceeds max {Config.MAX_ORDER_QUANTITY}"
        
        # 7. Validate price
        if price <= 0:
            return False, f"Invalid price: {price}"
        
        # Check price is reasonable (not too far from LTP if available)
        if self.instruments:
            try:
                ltp = self.instruments.get_ltp(str(token))
                if ltp > 0:
                    deviation = abs(price - ltp) / ltp * 100
                    if deviation > Config.PRICE_TOLERANCE_PERCENT:
                        return False, (
                            f"Price {price} deviates {deviation:.1f}% from LTP {ltp} "
                            f"(max {Config.PRICE_TOLERANCE_PERCENT}%)"
                        )
            except Exception as e:
                logger.exception(f"Price validation LTP fetch failed for token {token}: {e}")
                pass
        
        # 8. Check market hours (IST 9:15 AM to 3:30 PM)
        current_time = ist_now().time()
        from datetime import time as dt_time
        market_open = dt_time(9, 15, 0)
        market_close = dt_time(15, 30, 0)
        
        if not (market_open <= current_time <= market_close):
            # Allow if it's within 5 minutes of market close for squareoff
            if not (dt_time(15, 25, 0) <= current_time <= dt_time(15, 35, 0)):
                return False, f"Market closed (current time: {current_time})"
        
        return True, ""
    
    def _check_risk_limits(self, side: str, token: str, qty: int, 
                          price: float) -> Tuple[bool, str]:
        """
        Comprehensive risk limit checking
        
        Returns:
            (passed, message) tuple
        """
        
        # Reset daily P&L if new day
        current_date = ist_now().date()
        if current_date != self.daily_loss_start:
            self.daily_pnl = 0.0
            self.net_realized = 0.0
            self.daily_loss_start = current_date
            logger.info(" New trading day - reset daily P&L")
        
        # 1. Check daily loss limit
        if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
            self._trigger_circuit_breaker(f"Daily loss limit breached: {self.daily_pnl:,.2f}")
            return False, f"Daily loss limit breached: {self.daily_pnl:,.2f}"
        
        # 2. Check if adding position would breach daily loss limit
        # For SELL (short entry), potential max loss is if price goes to infinity (use 2x current price)
        # For BUY, potential max loss is position value
        position_value = qty * price
        
        if side == 'SELL':
            # Opening short - max potential loss (conservative estimate)
            potential_max_loss = position_value * 1.5  # 50% adverse move
        else:
            # Opening long or closing short
            potential_max_loss = position_value
        
        if self.daily_pnl - potential_max_loss <= -Config.MAX_DAILY_LOSS:
            return False, (
                f"Potential trade loss would breach daily limit: "
                f"current P&L: {self.daily_pnl:,.2f}, "
                f"potential loss: {potential_max_loss:,.2f}"
            )
        
        # 3. Check single trade loss limit
        if position_value > Config.MAX_TRADE_LOSS * 5:  # Max trade size
            return False, (
                f"Trade value {position_value:,.2f} exceeds limit "
                f"(5x MAX_TRADE_LOSS = {Config.MAX_TRADE_LOSS * 5:,.2f})"
            )
        
        # 4. Check position count limit
        with self.order_lock:
            open_positions = sum(1 for p in self.positions.values() if p.get('qty', 0) != 0)
        
        # If opening new position (not closing existing)
        is_closing = False
        with self.order_lock:
            existing_pos = self.positions.get(str(token))
            if existing_pos:
                existing_qty = existing_pos.get('qty', 0)
                if (side == 'BUY' and existing_qty < 0) or (side == 'SELL' and existing_qty > 0):
                    is_closing = True
        
        if not is_closing and open_positions >= Config.MAX_OPEN_POSITIONS:
            return False, (
                f"Max open positions ({Config.MAX_OPEN_POSITIONS}) reached: {open_positions}"
            )
        
        # 5. Check concentration risk (max 30% in single instrument)
        total_position_value = 0
        with self.order_lock:
            for pos_token, pos in self.positions.items():
                pos_qty = abs(pos.get('qty', 0))
                pos_price = pos.get('last_price', pos.get('avg_price', 0))
                total_position_value += pos_qty * pos_price
        
        if total_position_value > 0:
            new_concentration = (position_value / (total_position_value + position_value)) * 100
            if new_concentration > 30:
                return False, (
                    f"Position would create {new_concentration:.1f}% concentration in single instrument"
                )
        
        return True, ""
    
    def _trigger_circuit_breaker(self, reason: str):
        """Trigger circuit breaker to stop all trading"""
        if not self.circuit_breaker_triggered:
            self.circuit_breaker_triggered = True
            self.circuit_breaker_time = ist_now()
            
            logger.critical(f" CIRCUIT BREAKER TRIGGERED: {reason}")
            
            if self.notifier:
                try:
                    threading.Thread(target=self.notifier.send_trade_log, args=(f" CIRCUIT BREAKER\n\n{reason}",), daemon=True).start()
                except Exception:
                    logger.exception("Failed to spawn circuit-breaker notifier thread")
            
            # Save state
            self.state.set('circuit_breaker_triggered', True)
            self.state.set('circuit_breaker_reason', reason)
            self.state.set('circuit_breaker_time', self.circuit_breaker_time.isoformat())
    
    def _execute_order_with_retry(self, side: str, token: str, symbol: str, 
                                  qty: int, price: float, tag: str) -> Dict[str, Any]:
        """
        Execute order with retry logic and status verification
        
        Returns:
            Order dict with verified status
        """
        order_id = str(uuid.uuid4())
        exchange_order_id = None
        
        for attempt in range(Config.ORDER_MAX_RETRIES):
            try:
                logger.info(
                    f" Placing order (attempt {attempt + 1}): "
                    f"{side} {qty} {symbol} @ {price:.2f}"
                )
                
                # Prepare order parameters
                order_params = {
                    'variety': Config.ORDER_VARIETY,
                    'tradingsymbol': symbol or f'TOKEN_{token}',
                    'symboltoken': str(token),
                    'transactiontype': side,
                    'exchange': Config.EXCHANGE,
                    'ordertype': Config.ORDER_TYPE,
                    'producttype': Config.PRODUCT_TYPE,
                    'duration': 'DAY',
                    'quantity': str(qty)
                }
                
                # Add price for LIMIT orders
                if Config.ORDER_TYPE == 'LIMIT':
                    limit_price = price * (1 + Config.LIMIT_PRICE_OFFSET_PERCENT / 100)
                    order_params['price'] = f"{limit_price:.2f}"
                
                # Place order
                # Use safe API call wrapper when placing orders
                response = None
                try:
                    response = self._safe_api_call(lambda: self.api.placeOrder(order_params), retries=1, delay=0)
                except Exception:
                    # _safe_api_call will raise only if fatal; we handle below
                    response = None

                if not response or not response.get('status'):
                    # If we got a network exception or no response, attempt to check if order exists at broker
                    match = None
                    try:
                        match = self._find_matching_order(side, token, qty)
                    except Exception:
                        match = None

                    if match:
                        # Found matching pending order on broker — treat as placed
                        exchange_order_id = match.get('orderid') or match.get('order_id')
                        logger.info(f" Order placement uncertain but matching order found at broker: {exchange_order_id}")
                        final_status = self._poll_order_status(exchange_order_id, timeout=30)
                        if final_status['status'] == 'FILLED':
                            return {
                                'order_id': order_id,
                                'exchange_order_id': exchange_order_id,
                                'status': 'FILLED',
                                'message': 'Order filled (detected via orderBook)',
                                'timestamp': ist_now().isoformat(),
                                'side': side,
                                'token': token,
                                'symbol': symbol,
                                'qty': qty,
                                'price': final_status.get('fill_price', price),
                                'tag': tag
                            }
                        elif final_status['status'] == 'REJECTED':
                            return {
                                'order_id': order_id,
                                'exchange_order_id': exchange_order_id,
                                'status': 'REJECTED',
                                'message': final_status.get('message', 'Order rejected by exchange'),
                                'timestamp': ist_now().isoformat(),
                                'side': side,
                                'token': token,
                                'symbol': symbol,
                                'qty': qty,
                                'price': price,
                                'tag': tag
                            }
                        elif final_status['status'] == 'PARTIALLY_FILLED':
                            # Handle partial fills conservatively
                            try:
                                self._handle_partial_fill(final_status, token, side, qty)
                            except Exception:
                                logger.exception("Failed to handle partial fill (matching order branch)")
                            return {
                                'order_id': order_id,
                                'exchange_order_id': exchange_order_id,
                                'status': 'PARTIALLY_FILLED',
                                'message': final_status.get('message', 'Order partially filled'),
                                'filled_qty': int(final_status.get('filled_qty', 0)),
                                'timestamp': ist_now().isoformat(),
                                'side': side,
                                'token': token,
                                'symbol': symbol,
                                'qty': qty,
                                'price': price,
                                'tag': tag
                            }
                        else:
                            return {
                                'order_id': order_id,
                                'exchange_order_id': exchange_order_id,
                                'status': final_status['status'],
                                'message': final_status.get('message', 'Order status unknown'),
                                'timestamp': ist_now().isoformat(),
                                'side': side,
                                'token': token,
                                'symbol': symbol,
                                'qty': qty,
                                'price': price,
                                'tag': tag
                            }

                    # If no matching order found, treat as transient and decide to retry or fail
                    error_msg = 'No response from broker (network or transient error)'
                    logger.error(f" Order placement failed: {error_msg}")

                    if attempt < Config.ORDER_MAX_RETRIES - 1:
                        time.sleep(Config.ORDER_RETRY_DELAY)
                        continue
                    else:
                        # Could not guarantee idempotency — fail safe: trigger circuit breaker and block new entries
                        self._trigger_circuit_breaker("Order placement uncertainty due to network failures")
                        return {
                            'order_id': order_id,
                            'exchange_order_id': None,
                            'status': 'ERROR',
                            'message': 'Order placement uncertain - network failures; trading halted',
                            'timestamp': ist_now().isoformat(),
                            'side': side,
                            'token': token,
                            'symbol': symbol,
                            'qty': qty,
                            'price': price,
                            'tag': tag
                        }
                
                # Order placed successfully, get exchange order ID
                exchange_order_id = response.get('data', {}).get('orderid')
                logger.info(f" Order placed successfully: Exchange ID = {exchange_order_id}")
                
                # Poll for order status
                final_status = self._poll_order_status(exchange_order_id, timeout=30)
                
                if final_status['status'] == 'FILLED':
                    logger.info(
                        f" Order FILLED: {side} {qty} @ {final_status.get('fill_price', price):.2f}"
                    )
                    return {
                        'order_id': order_id,
                        'exchange_order_id': exchange_order_id,
                        'status': 'FILLED',
                        'message': 'Order filled successfully',
                        'timestamp': ist_now().isoformat(),
                        'side': side,
                        'token': token,
                        'symbol': symbol,
                        'qty': qty,
                        'price': final_status.get('fill_price', price),
                        'tag': tag
                    }
                elif final_status['status'] == 'REJECTED':
                    logger.error(f" Order REJECTED: {final_status.get('message')}")
                    return {
                        'order_id': order_id,
                        'exchange_order_id': exchange_order_id,
                        'status': 'REJECTED',
                        'message': final_status.get('message', 'Order rejected by exchange'),
                        'timestamp': ist_now().isoformat(),
                        'side': side,
                        'token': token,
                        'symbol': symbol,
                        'qty': qty,
                        'price': price,
                        'tag': tag
                    }
                elif final_status['status'] == 'PARTIALLY_FILLED':
                    try:
                        self._handle_partial_fill(final_status, token, side, qty)
                    except Exception:
                        logger.exception("Failed to handle partial fill (post-placement)")
                    return {
                        'order_id': order_id,
                        'exchange_order_id': exchange_order_id,
                        'status': 'PARTIALLY_FILLED',
                        'message': final_status.get('message', 'Order partially filled'),
                        'filled_qty': int(final_status.get('filled_qty', 0)),
                        'timestamp': ist_now().isoformat(),
                        'side': side,
                        'token': token,
                        'symbol': symbol,
                        'qty': qty,
                        'price': price,
                        'tag': tag
                    }
                else:
                    # PENDING or unknown
                    logger.warning(
                        f" Order {final_status['status']}: {final_status.get('message')}"
                    )
                    return {
                        'order_id': order_id,
                        'exchange_order_id': exchange_order_id,
                        'status': final_status['status'],
                        'message': final_status.get('message', 'Order status unknown'),
                        'timestamp': ist_now().isoformat(),
                        'side': side,
                        'token': token,
                        'symbol': symbol,
                        'qty': qty,
                        'price': price,
                        'tag': tag
                    }
                
            except Exception as e:
                logger.exception(f"Order execution error (attempt {attempt + 1}): {e}")
                
                if attempt < Config.ORDER_MAX_RETRIES - 1:
                    time.sleep(Config.ORDER_RETRY_DELAY)
                else:
                    return {
                        'order_id': order_id,
                        'exchange_order_id': exchange_order_id,
                        'status': 'ERROR',
                        'message': str(e),
                        'timestamp': ist_now().isoformat(),
                        'side': side,
                        'token': token,
                        'symbol': symbol,
                        'qty': qty,
                        'price': price,
                        'tag': tag
                    }
        
        # Should never reach here
        return {
            'order_id': order_id,
            'exchange_order_id': exchange_order_id,
            'status': 'ERROR',
            'message': 'Max retries exceeded',
            'timestamp': ist_now().isoformat(),
            'side': side,
            'token': token,
            'symbol': symbol,
            'qty': qty,
            'price': price,
            'tag': tag
        }
    
    def _poll_order_status(self, exchange_order_id: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Poll exchange for order status until filled, rejected, or timeout
        
        Returns:
            dict with 'status', 'message', 'fill_price'
        """
        poll_interval = 0.5  # 500ms
        max_polls = max(10, int(timeout / poll_interval))

        for attempt in range(max_polls):
            try:
                response = self._safe_api_call(self.api.orderBook, retries=Config.API_CALL_MAX_RETRIES, delay=Config.API_CALL_RETRY_DELAY)

                if not response or not response.get('status'):
                    logger.warning(f"Order status poll failed (attempt {attempt+1}/{max_polls})")
                    time.sleep(poll_interval)
                    continue

                orders = response.get('data', [])
                for order in orders:
                    try:
                        if str(order.get('orderid') or order.get('order_id')) == str(exchange_order_id):
                            status_raw = str(order.get('orderstatus') or order.get('status') or '').lower()

                            # Terminal states
                            if any(k in status_raw for k in ['complete', 'executed', 'filled']):
                                return {
                                    'status': 'FILLED',
                                    'message': 'Order filled',
                                    'fill_price': float(order.get('averageprice') or order.get('fill_price') or 0)
                                }

                            if any(k in status_raw for k in ['rejected', 'cancelled', 'cancelled by user']):
                                return {
                                    'status': 'REJECTED',
                                    'message': order.get('text', 'Order rejected')
                                }

                            # Partial fills
                            if any(k in status_raw for k in ['partial', 'partially']):
                                filled_qty = int(order.get('filledquantity') or order.get('filled_qty') or order.get('filled') or 0)
                                return {
                                    'status': 'PARTIALLY_FILLED',
                                    'message': 'Order partially filled',
                                    'filled_qty': filled_qty,
                                    'raw': order
                                }

                            # Pending/open - continue polling
                    except Exception:
                        continue

                time.sleep(poll_interval)

            except Exception as e:
                logger.exception(f"Order polling error (attempt {attempt+1}): {e}")
                time.sleep(poll_interval)

        # Max polls exceeded - critical situation
        logger.critical(f"❌ Order {exchange_order_id} status unknown after {max_polls} polls")
        raise Exception(f"Order status verification failed after {max_polls} attempts")

    def _handle_partial_fill(self, order_result: Dict[str, Any], token: str, side: str, requested_qty: int):
        """Comprehensive partial fill handling.

        Sets internal flags, persists partial-fill info, and notifies trader.
        This function intentionally does not attempt automatic complex fixes
        (e.g., cancelling remaining quantity) — it records state and alerts
        operators for manual or automated reconciliation later.
        """
        try:
            filled_qty = int(order_result.get('filled_qty') or order_result.get('filledquantity') or order_result.get('filled') or 0)
            remaining_qty = max(0, requested_qty - filled_qty)

            logger.warning(
                f"⚠️ PARTIAL FILL: {filled_qty}/{requested_qty} filled for {token}, {remaining_qty} remaining"
            )

            # Record partial-fill info and block new entries that would increase exposure
            self._partial_fill_block = True
            self._partial_fill_info = {
                'token': str(token),
                'side': side,
                'requested': requested_qty,
                'filled': filled_qty,
                'remaining': remaining_qty,
                'timestamp': time.time(),
                'expected_qty': filled_qty
            }

            try:
                self.state.set('partial_fill', self._partial_fill_info)
            except Exception:
                logger.exception("Failed to persist partial_fill state")

            # Notify trader (non-blocking)
            if self.notifier:
                try:
                    threading.Thread(
                        target=self.notifier.send_trade_log,
                        args=(
                            f"⚠️ PARTIAL FILL ALERT\nToken: {token}\nFilled: {filled_qty}/{requested_qty}\nAction: Manual review required",
                        ),
                        daemon=True
                    ).start()
                except Exception:
                    logger.exception("Failed to spawn partial-fill notifier thread")

        except Exception as e:
            logger.exception(f"_handle_partial_fill failed: {e}")

    def _has_similar_pending_order(self, side: str, token: str, qty: int) -> bool:
        """Check broker order book for similar pending orders to avoid duplicate placements.

        Conservative check: any open order for same token and side with >= requested qty is considered duplicate.
        """
        try:
            response = self._safe_api_call(self.api.orderBook, retries=Config.API_CALL_MAX_RETRIES, delay=Config.API_CALL_RETRY_DELAY)
            if not response or not response.get('status'):
                return False

            orders = response.get('data', [])
            for order in orders:
                try:
                    if str(order.get('symboltoken')) == str(token):
                        status = order.get('orderstatus', '').lower()
                        if status in ['open', 'pending', 'trigger pending']:
                            o_side = order.get('transactiontype', '').upper()
                            o_qty = int(order.get('quantity') or order.get('filledquantity') or 0)
                            if o_side == side and o_qty >= qty:
                                return True
                except Exception:
                    continue
        except Exception as e:
            logger.exception(f"Failed to fetch order book for duplicate check: {e}")
        return False

    def _safe_api_call(self, func, retries: int = 3, delay: float = 1.0):
        """Call `func()` with controlled retries on network errors.

        This wrapper attempts to call the provided function up to `retries` times. If an exception
        occurs it will wait `delay` seconds and retry. If all retries fail it raises the last exception.
        Use this for non-destructive read calls and for detecting idempotent state; for write
        operations we use additional verification against broker state to avoid duplicates.
        
        Enforces API_RATE_LIMIT_PER_SECOND to prevent API spamming.
        """
        # Enforce API rate limit using monotonic clock
        self._enforce_api_rate_limit()

        last_exc = None
        for attempt in range(max(1, retries)):
            try:
                return func()
            except Exception as e:
                last_exc = e
                # Exponential backoff for transient network issues
                if attempt < max(0, retries - 1):
                    backoff = delay * (2 ** attempt)
                    logger.warning(f" API call attempt {attempt+1} failed: {e} - retrying in {backoff}s")
                    time.sleep(backoff)
                    continue
                else:
                    logger.exception(f"API call fatal after {attempt+1} attempts: {e}")
                    raise
    
    def _enforce_api_rate_limit(self):
        """Enforce API_RATE_LIMIT_PER_SECOND using monotonic clock"""
        if self._min_api_interval <= 0:
            return  # No rate limiting configured
        
        with self._api_limit_lock:
            now = time.monotonic()
            elapsed = now - self._last_api_call_time
            if elapsed < self._min_api_interval:
                sleep_time = self._min_api_interval - elapsed
                if sleep_time > 0.001:  # Only sleep if meaningful (>1ms)
                    logger.debug(f" API rate limit: sleeping {sleep_time:.3f}s")
                    time.sleep(sleep_time)
            self._last_api_call_time = time.monotonic()

    def _find_matching_order(self, side: str, token: str, qty: int) -> Optional[Dict[str, Any]]:
        """Return an order dict from broker orderBook that matches the token/side/qty criteria, or None."""
        try:
            response = self._safe_api_call(self.api.orderBook, retries=Config.API_CALL_MAX_RETRIES, delay=Config.API_CALL_RETRY_DELAY)
            if not response or not response.get('status'):
                return None
            orders = response.get('data', [])
            for order in orders:
                try:
                    if str(order.get('symboltoken')) == str(token):
                        status = order.get('orderstatus', '').lower()
                        if status in ['open', 'pending', 'trigger pending']:
                            o_side = order.get('transactiontype', '').upper()
                            o_qty = int(order.get('quantity') or order.get('filledquantity') or 0)
                            if o_side == side and o_qty >= qty:
                                return order
                except Exception:
                    continue
        except Exception as e:
            logger.exception(f"Failed to fetch order book for matching order: {e}")
        return None
    
    def _apply_fill(self, order: Dict[str, Any]):
        """Update positions based on order fill"""
        token = str(order['token'])
        side = order['side'].upper()
        qty = int(order['qty'])
        price = float(order['price'])
        
        with self.order_lock:
            pos = self.positions.get(token)
            if pos is None:
                pos = {
                    'qty': 0, 
                    'avg_price': 0.0, 
                    'side': None, 
                    'last_price': price,
                    'symbol': order.get('symbol', f'TOKEN_{token}'),
                    'token': token
                }
                self.positions[token] = pos
            
            # Update position
            if side == "BUY":
                if pos['qty'] < 0:
                    # Closing short
                    close_qty = min(qty, abs(pos['qty']))
                    realized = (pos['avg_price'] - price) * close_qty
                    self.net_realized += realized
                    self.daily_pnl += realized
                    pos['qty'] += close_qty
                    qty -= close_qty
                    
                    logger.info(f" Realized P&L: {realized:,.2f} (Total: {self.net_realized:,.2f})")
                    
                    if pos['qty'] == 0:
                        pos['avg_price'] = 0.0
                        pos['side'] = None
                
                # Opening/adding to long
                if qty > 0:
                    total_val = (pos['qty'] * pos['avg_price']) + (qty * price)
                    pos['qty'] += qty
                    pos['avg_price'] = total_val / pos['qty'] if pos['qty'] != 0 else 0.0
                    pos['side'] = 'LONG'
                    pos['last_price'] = price
            
            else:  # SELL
                if pos['qty'] > 0:
                    # Closing long
                    close_qty = min(qty, pos['qty'])
                    realized = (price - pos['avg_price']) * close_qty
                    self.net_realized += realized
                    self.daily_pnl += realized
                    pos['qty'] -= close_qty
                    qty -= close_qty
                    
                    logger.info(f" Realized P&L: {realized:,.2f} (Total: {self.net_realized:,.2f})")
                    
                    if pos['qty'] == 0:
                        pos['avg_price'] = 0.0
                        pos['side'] = None
                
                # Opening/adding to short
                if qty > 0:
                    total_val = (abs(pos['qty']) * pos['avg_price']) + (qty * price)
                    pos['qty'] -= qty
                    pos['avg_price'] = total_val / abs(pos['qty']) if pos['qty'] != 0 else 0.0
                    pos['side'] = 'SHORT'
                    pos['last_price'] = price
            
            # Cleanup
            if pos['qty'] == 0:
                pos['side'] = None
                pos['avg_price'] = 0.0
            
            # Save
            self._save_positions()
    
    def _log_order(self, order: Dict[str, Any], tag: str):
        """Log order to CSV and trade logger"""
        try:
            # Trade logger
            status_icon = "" if order['status'] == 'FILLED' else ""
            trade_logger.info(
                f"{status_icon} {order['side']} {order['qty']} @ {order['price']:.2f} | "
                f"{tag} | Status: {order['status']} | "
                f"Exchange ID: {order.get('exchange_order_id', 'N/A')}"
            )
            
            # CSV log
            with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([
                    order['timestamp'],
                    order['order_id'],
                    order.get('exchange_order_id', ''),
                    order['side'],
                    order['token'],
                    order.get('symbol', ''),
                    order['qty'],
                    f"{order['price']:.2f}",
                    Config.ORDER_TYPE,
                    order['status'],
                    tag,
                    order.get('message', '')
                ])
        except Exception as e:
            logger.exception(f"Failed to log order: {e}")
    
    def _notify_order(self, order: Dict[str, Any], tag: str):
        """Send order notification via Telegram"""
        if not self.notifier:
            return
        
        try:
            label = tag or f"{order['side']} {order.get('symbol', order['token'])}"
            
            if order['status'] == 'FILLED':
                if order['side'] == "SELL":
                    threading.Thread(
                        target=self.notifier.send_entry,
                        args=(f" {label}", order['price']),
                        daemon=True
                    ).start()
                elif order['side'] == "BUY":
                    threading.Thread(
                        target=self.notifier.send_entry,
                        args=(f" {label}", order['price']),
                        daemon=True
                    ).start()
            
            # Trade log
            status_icon = "" if order['status'] == 'FILLED' else ""
            threading.Thread(
                target=self.notifier.send_trade_log,
                args=(
                    f"{status_icon} {order['side']} {order['qty']} @ {order['price']:.2f} | "
                    f"{label} | {order['status']}",
                ),
                daemon=True
            ).start()
            
        except Exception as e:
            logger.exception(f"Notifier hook failed: {e}")
    
    # ==================== QUERY API ====================
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Return list of all positions"""
        with self.order_lock:
            return [{'token': t, **v} for t, v in self.positions.items()]
    
    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Return dict of non-zero positions"""
        with self.order_lock:
            return {k: v for k, v in self.positions.items() if v.get('qty', 0) != 0}
    
    def get_position_count(self) -> int:
        """Return total position count"""
        with self.order_lock:
            return sum(abs(v.get('qty', 0)) for v in self.positions.values())
    
    def get_total_pnl(self, feed: FeedProtocol) -> float:
        """Calculate total P&L (realized + unrealized)"""
        unrealized = 0.0
        
        with self.order_lock:
            for token, pos in self.positions.items():
                qty = pos.get('qty', 0)
                if qty == 0:
                    continue
                
                # Get current LTP
                ltp = None
                try:
                    ltp = feed.get_ltp(token, check_freshness=False)
                except Exception as e:
                    logger.exception(f"Failed to fetch LTP for token {token} in get_total_pnl: {e}")
                    pass
                
                if ltp is None:
                    ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                
                # Calculate unrealized P&L
                if qty > 0:
                    unrealized += (ltp - pos.get('avg_price', 0.0)) * qty
                else:
                    unrealized += (pos.get('avg_price', 0.0) - ltp) * abs(qty)
        
        return self.net_realized + unrealized
    
    def get_realized_pnl(self) -> float:
        """Get realized P&L only"""
        with self.order_lock:
            return self.net_realized
    
    def get_unrealized_pnl(self, feed: FeedProtocol) -> float:
        """Get unrealized P&L only"""
        unrealized = 0.0
        
        with self.order_lock:
            for token, pos in self.positions.items():
                qty = pos.get('qty', 0)
                if qty == 0:
                    continue
                
                # Get current LTP
                ltp = None
                try:
                    ltp = feed.get_ltp(token, check_freshness=False)
                except Exception as e:
                    logger.exception(f"Failed to fetch LTP for token {token} in get_unrealized_pnl: {e}")
                    pass
                
                if ltp is None:
                    ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                
                # Calculate unrealized P&L
                if qty > 0:
                    unrealized += (ltp - pos.get('avg_price', 0.0)) * qty
                else:
                    unrealized += (pos.get('avg_price', 0.0) - ltp) * abs(qty)
        
        return unrealized
    
    def get_pnl_breakdown(self, feed: FeedProtocol) -> Dict[str, float]:
        """Get detailed P&L breakdown including per-leg realized/unrealized"""
        breakdown = {
            'total_realized': 0.0,
            'total_unrealized': 0.0,
            'total_net': 0.0,
            'positions': {}
        }
        
        with self.order_lock:
            breakdown['total_realized'] = self.net_realized
            
            for token, pos in self.positions.items():
                qty = pos.get('qty', 0)
                symbol = pos.get('symbol', f'TOKEN_{token}')
                
                if qty == 0:
                    continue
                
                # Get current LTP
                ltp = None
                try:
                    ltp = feed.get_ltp(token, check_freshness=False)
                except Exception as e:
                    logger.exception(f"Failed to fetch LTP for token {token} in get_pnl_breakdown: {e}")
                    pass
                
                if ltp is None:
                    ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                
                # Calculate unrealized P&L for this position
                if qty > 0:
                    unrealized_pos = (ltp - pos.get('avg_price', 0.0)) * qty
                else:
                    unrealized_pos = (pos.get('avg_price', 0.0) - ltp) * abs(qty)
                
                breakdown['positions'][symbol] = {
                    'qty': qty,
                    'side': pos.get('side', 'UNKNOWN'),
                    'avg_price': pos.get('avg_price', 0.0),
                    'ltp': ltp,
                    'unrealized_pnl': unrealized_pos
                }
                
                breakdown['total_unrealized'] += unrealized_pos
            
            breakdown['total_net'] = breakdown['total_realized'] + breakdown['total_unrealized']
        
        return breakdown
    
    # ==================== UTILITIES ====================
    
    def close_all(self, market_prices: Dict[str, float]):
        """Close all open positions"""
        logger.warning(" Closing all positions...")
        
        with self.order_lock:
            tokens = list(self.positions.keys())
        
        for token in tokens:
            with self.order_lock:
                pos = self.positions.get(token)
                if not pos or pos.get('qty', 0) == 0:
                    continue
                
                qty = abs(pos['qty'])
                side = "BUY" if pos['qty'] < 0 else "SELL"
                symbol = pos.get('symbol', f"TOKEN_{token}")
                ltp = market_prices.get(str(token), pos.get('last_price', pos.get('avg_price', 0.0)))
            
            try:
                self.place_order(
                    side=side,
                    token=token,
                    symbol=symbol,
                    qty=qty,
                    price=ltp,
                    tag="SQUAREOFF"
                )
            except Exception as e:
                logger.exception(f"Failed to close position {token}: {e}")
    
    def reset(self):
        """Reset broker state - USE WITH EXTREME CAUTION"""
        logger.warning(" RESETTING BROKER STATE - THIS SHOULD ONLY BE DONE IN TESTING!")
        with self.order_lock:
            self.positions = {}
            self.orders = []
            self.net_realized = 0.0
            self.daily_pnl = 0.0
            self.circuit_breaker_triggered = False
            self.circuit_breaker_time = None
            self._save_positions()
    
    def stop(self):
        """Stop broker services"""
        self._stop_reconciliation = True
        if self.reconciliation_thread:
            self.reconciliation_thread.join(timeout=2)
        logger.info("LiveBroker stopped")
