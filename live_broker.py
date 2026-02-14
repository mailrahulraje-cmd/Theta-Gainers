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
from contract import BrokerProtocol, OrderDict, FeedProtocol
from core.execution_gateway import get_execution_gateway

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
        if Config.ENABLE_POSITION_RECONCILIATION:
            self._start_reconciliation_thread()
        
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
            
        except Exception as e:
            logger.exception(f"Failed to restore positions: {e}")
    
    def _sync_positions_from_broker(self):
        """Sync positions from broker API"""
        try:
            response = self.api.position()
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
    
    def _reconcile_positions(self):
        """Reconcile local positions with broker positions"""
        try:
            logger.info(" Reconciling positions with broker...")
            
            response = self.api.position()
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
                        self.notifier.send_trade_log(
                            f" Position Reconciliation: {len(discrepancies)} discrepancies found"
                        )
                else:
                    logger.info(" Reconciliation: All positions match")
            
            self.last_reconciliation = ist_now()
            
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
                self.notifier.send_trade_log(" Order rejected: Circuit breaker active")
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
        allowed, reason = self.gateway.validate_order(
            symbol=symbol or f"Token-{token}",
            transaction_type=side,
            quantity=qty,
            price=price,
            order_type='MARKET'
        )
        
        if not allowed:
            logger.error(f" Order REJECTED by ExecutionGateway: {reason}")
            if self.notifier:
                self.notifier.send_trade_log(f" Order rejected: {reason}")
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
                self.notifier.send_trade_log(f" Risk limit: {limit_msg}")
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
        
        # Place order with retries and status verification
        order_result = self._execute_order_with_retry(
            side, token, symbol, qty, price, tag
        )
        
        # ==================== TIMING VALIDATION ====================
        if Config.ENABLE_TIMEOUT_PROTECTION:
            order_duration = time.time() - order_start_time
            if order_duration > Config.MAX_ORDER_PLACEMENT_TIME:
                logger.warning(
                    f" Order placement took {order_duration:.2f}s "
                    f"(threshold: {Config.MAX_ORDER_PLACEMENT_TIME}s)"
                )
                if self.notifier:
                    self.notifier.send_trade_log(
                        f" Slow order: {order_duration:.2f}s for {tag}"
                    )
        
        # Log and save
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
                        except:
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
            except:
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
                self.notifier.send_trade_log(f" CIRCUIT BREAKER\n\n{reason}")
            
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
                response = self.api.placeOrder(order_params)
                
                if not response or not response.get('status'):
                    error_msg = response.get('message', 'Unknown error') if response else 'No response'
                    logger.error(f" Order placement failed: {error_msg}")
                    
                    # Check if we should retry
                    if 'insufficient' in error_msg.lower() or 'margin' in error_msg.lower():
                        # Margin error - don't retry, trigger circuit breaker
                        self._trigger_circuit_breaker(f"Insufficient margin: {error_msg}")
                        return {
                            'order_id': order_id,
                            'exchange_order_id': None,
                            'status': 'REJECTED',
                            'message': error_msg,
                            'timestamp': ist_now().isoformat(),
                            'side': side,
                            'token': token,
                            'symbol': symbol,
                            'qty': qty,
                            'price': price,
                            'tag': tag
                        }
                    
                    # Network/temporary error - retry
                    if attempt < Config.ORDER_MAX_RETRIES - 1:
                        time.sleep(Config.ORDER_RETRY_DELAY)
                        continue
                    else:
                        return {
                            'order_id': order_id,
                            'exchange_order_id': None,
                            'status': 'REJECTED',
                            'message': error_msg,
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
                else:
                    # PENDING or PARTIALLY_FILLED
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
        start_time = time.time()
        poll_interval = 0.5  # 500ms
        
        while time.time() - start_time < timeout:
            try:
                # Fetch order book
                response = self.api.orderBook()
                
                if response and response.get('status'):
                    orders = response.get('data', [])
                    
                    # Find our order
                    for order in orders:
                        if order.get('orderid') == exchange_order_id:
                            status = order.get('orderstatus', '').lower()
                            
                            if status in ['complete', 'executed']:
                                return {
                                    'status': 'FILLED',
                                    'message': 'Order filled',
                                    'fill_price': float(order.get('averageprice', 0))
                                }
                            elif status in ['rejected', 'cancelled']:
                                return {
                                    'status': 'REJECTED',
                                    'message': order.get('text', 'Order rejected')
                                }
                            elif status in ['open', 'pending', 'trigger pending']:
                                # Order still pending, continue polling
                                pass
                            else:
                                logger.warning(f"Unknown order status: {status}")
                
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.exception(f"Error polling order status: {e}")
                time.sleep(poll_interval)
        
        # Timeout
        logger.warning(f" Order status polling timeout for {exchange_order_id}")
        return {
            'status': 'PENDING',
            'message': 'Status polling timeout - order may still be pending'
        }
    
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
                except:
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
                except:
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
                except:
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
