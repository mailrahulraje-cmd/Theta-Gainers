import threading
import time
from datetime import datetime
from config import Config
from constants import (
    PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1,
    PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED
)
from utils.logger import logger
from utils.order_journal import get_order_journal
from utils.phase_manager import PhaseManager, LegState
from utils.safety_validator import SafetyValidator
from contract import StateProtocol, FeedProtocol, BrokerProtocol, NotifierProtocol
from core.trade_leg_manager import TradeLegManager
from contract import TradeLegV1
from core.state_schema import validate_state_schema


def ist_now() -> datetime:
    return datetime.now(Config.TZ)

class StrategyEngine:
    def __init__(self, feed: FeedProtocol, instruments, broker: BrokerProtocol, state: StateProtocol, notifier: NotifierProtocol = None):
        """
        feed: UnifiedFeed instance
        instruments: InstrumentMaster instance
        broker: PaperBroker-like instance
        state: StrategyState-like instance (expects get/set/update)
        notifier: optional Telegram notifier (has send_entry/send_exit/heartbeat/send_strike_selection/send_ws_status/send_trade_log)
        """
        # ================================================================
        # PHASE 1: NOTIFIER CONTRACT ASSERTION
        # ================================================================
        # Validate notifier implements NotifierProtocol if provided
        if notifier is not None:
            required_methods = [
                'send_entry', 'send_exit', 'send_trade_log',
                'send_strike_selection', 'send_phase_change',
                'send_lock_event', 'send_trade_entry',
                'send_trailing_sl_update', 'heartbeat'
            ]
            
            missing_methods = []
            for method_name in required_methods:
                if not hasattr(notifier, method_name) or not callable(getattr(notifier, method_name)):
                    missing_methods.append(method_name)
            
            if missing_methods:
                logger.error("=" * 80)
                logger.error("[ERROR] NOTIFIER CONTRACT ASSERTION FAILED")
                logger.error("=" * 80)
                logger.error(f"Notifier missing required methods: {missing_methods}")
                logger.error("Notifier will be DISABLED to prevent crashes")
                logger.error("=" * 80)
                notifier = None  # Disable notifier
            else:
                logger.info("=" * 80)
                logger.info("[OK] NOTIFIER CONTRACT ASSERTION PASSED")
                logger.info("=" * 80)
                logger.info(f"All {len(required_methods)} required methods verified")
                logger.info("=" * 80)
        # ================================================================
        
        self.feed = feed
        self.instruments = instruments
        self.broker = broker
        self.state = state
        self.notifier = notifier
        
        # Initialize PhaseManager for centralized phase and leg state tracking
        self.phase_manager = PhaseManager(logger=logger)
        
        # Initialize SafetyValidator for live trading safety checks (7 requirements)
        self.safety_validator = SafetyValidator(logger_instance=logger)
        # TradeLegManager for type-safe leg storage used by engine logic
        self.trade_leg_manager = TradeLegManager()


        self.threads = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # wire tick callback
        try:
            self.feed.set_tick_callback(self._on_tick)
        except Exception:
            logger.exception("Failed to set feed tick callback")

        # local runtime state
        self.running = False
        
        # -------------------------
        # TRAILING STOP-LOSS ENHANCEMENT (SELL LEGS ONLY)
        # -------------------------
        # Tracking for independent SELL CE and SELL PE legs
        # All changes are strictly additive - existing logic remains untouched
        
        # Track most adverse price during observation window (12:00-14:00)
        # For sold options, adverse means highest price reached
        self._trailing_sell_ce_adverse_price = None  # Highest price during 12:00-14:00
        self._trailing_sell_pe_adverse_price = None  # Highest price during 12:00-14:00
        
        # Flag to indicate observation window completed (frozen after 14:00)
        self._trailing_observation_completed = False
        
        # Flag to indicate trailing is active (from 14:15 onwards)
        self._trailing_active = False
        
        # Lock for thread-safe tracking updates
        self._trailing_lock = threading.Lock()
        
        # -------------------------
        # LTP unavailability safeguards
        # -------------------------
        # Track when tokens were subscribed to allow first-tick grace period
        self._token_subscription_times = {}  # {token: subscription_timestamp}
        
        # Track last warning time per token to rate-limit warning logs
        self._last_warning_times = {}  # {token: last_warning_timestamp}
        
        # Grace period: allow this many seconds for first tick after subscription
        self._FIRST_TICK_GRACE_SECONDS = Config.FIRST_TICK_GRACE_SECONDS
        
        # Warning rate limit: log warnings at most once per this interval per token
        self._WARNING_RATE_LIMIT_SECONDS = 5.0
        
        # -------------------------
        # MAIN LOOP FREQUENCY CONTROL
        # -------------------------
        # Enforce fixed minimum iteration interval using monotonic clock
        self._loop_iteration_time = time.monotonic()
        self._min_loop_interval = Config.MAIN_LOOP_INTERVAL_SECONDS
        self._hard_exit_triggered = False  # Flag to track if hard exit was executed

    # -------------------------
    # lifecycle
    # -------------------------
    
    def _enforce_iteration_interval(self):
        """
        Enforce fixed minimum MAIN_LOOP_INTERVAL_SECONDS between iterations.
        Uses monotonic clock to prevent API spamming and high CPU usage.
        Sleep remaining duration if loop finishes early.
        """
        now = time.monotonic()
        elapsed = now - self._loop_iteration_time
        remaining = self._min_loop_interval - elapsed
        
        if remaining > 0.001:  # Only sleep if meaningful (>1ms)
            time.sleep(remaining)
        
        self._loop_iteration_time = time.monotonic()
    
    def _check_hard_exit(self) -> bool:
        """
        Check if hard exit time has been reached.
        If yes, trigger full flatten and disable new entries.
        Returns True if hard exit was triggered.
        
        FORENSIC AUDIT:
        - All positions closed are logged via OrderJournal
        - Timestamps and prices recorded for analysis
        """
        try:
            now = ist_now()
            current_time = now.time()
            hard_exit_time = Config.get_hard_exit_time()
            
            # In PAPER mode with IGNORE_MARKET_HOURS_IN_PAPER, skip hard exit enforcement
            if Config.TRADING_MODE == 'PAPER' and Config.IGNORE_MARKET_HOURS_IN_PAPER:
                return False  # Skip hard exit in paper mode with flag enabled
            
            if current_time >= hard_exit_time and not self._hard_exit_triggered:
                # REQUIREMENT 5: HARD EXIT IDEMPOTENCY - Ensure executes only once
                is_valid, idempotency_msg = self.safety_validator.validate_hard_exit_idempotency(
                    hard_exit_triggered=True,
                    state=self.state.get('trade_state', {}) or {}
                )
                logger.critical(f"HARD EXIT TRIGGERED: Current time {current_time} >= HARD_EXIT_TIME {hard_exit_time} | {idempotency_msg}")
                
                # Get order journal for logging
                journal = get_order_journal()
                
                # Mark hard exit as triggered
                self._hard_exit_triggered = True
                self.state.set('hard_exit_triggered', True)
                
                # Disable new entries permanently for this session
                if Config.DISABLE_ENTRIES_AFTER_HARD_EXIT:
                    logger.critical(" Hard exit: disabling new entries for this session")
                    self.state.set('hard_exit_no_new_entries', True)
                
                # Trigger full flatten if any positions are open
                try:
                    open_positions = {k: v for k, v in self.broker.positions.items() if v.get('qty', 0) != 0}
                    if open_positions:
                        logger.critical(f" Hard exit: closing {len(open_positions)} open positions")
                        
                        # Get market prices for closing (with retries)
                        market_prices = {}
                        for token in open_positions.keys():
                            for attempt in range(3):
                                try:
                                    ltp = self.feed.get_ltp(str(token), check_freshness=False)
                                    if ltp is None:
                                        ltp = open_positions[token].get('last_price', open_positions[token].get('avg_price', 0.0))
                                    market_prices[token] = ltp
                                    break
                                except Exception as e:
                                    if attempt == 2:
                                        # Last attempt failed, use average price
                                        market_prices[token] = open_positions[token].get('avg_price', 0.0)
                                        logger.warning(f"Failed to fetch LTP for {token} (attempt {attempt+1}), using avg price")
                                    else:
                                        time.sleep(0.1)
                        
                        # Close all positions with execution lock
                        if hasattr(self.broker, '_execution_lock'):
                            with self.broker._execution_lock:
                                self.broker.close_all(market_prices)
                        else:
                            self.broker.close_all(market_prices)
                        
                        # Log each position close to order journal
                        for token, pos in open_positions.items():
                            try:
                                close_price = market_prices.get(token, pos.get('avg_price', 0.0))
                                journal.log_hard_exit(
                                    symbol=pos.get('symbol', f'Token-{token}'),
                                    strike=0,  # Not applicable for all positions
                                    qty=abs(pos.get('qty', 0)),
                                    price=close_price
                                )
                            except Exception:
                                pass
                        
                        logger.critical(" Hard exit: all positions closed")
                        
                        # Verify positions are actually closed (broker is source of truth)
                        time.sleep(0.5)
                        try:
                            open_after = {k: v for k, v in self.broker.positions.items() if v.get('qty', 0) != 0}
                            if open_after:
                                logger.error(f"WARNING: {len(open_after)} positions still open after hard exit flatten!")
                                logger.error(f"Open positions: {list(open_after.keys())}")
                        except Exception:
                            pass
                    
                except Exception as e:
                    logger.exception(f"Error during hard exit flatten: {e}")
                
                # Send Telegram alert
                if self.notifier:
                    try:
                        msg = f"🔴 HARD EXIT EXECUTED\nTime: {current_time}\nAll open positions have been closed\nNo new entries permitted for this session"
                        self.notifier.send_trade_log(msg)
                    except Exception:
                        logger.exception("Failed to send hard exit notification")
                
                return True
            
        except Exception as e:
            logger.exception(f"Error in hard exit check: {e}")
        
        return self._hard_exit_triggered
    
    def start(self):
        logger.info("[START] Starting strategy...")
        # ensure state initialized
        if not self.state.get('initialized'):
            self.state.update({'phase': PHASE_INIT, 'initialized': True})

        # REQUIREMENT 3: RESTART RECOVERY - Check for open positions at broker
        try:
            logger.info("[SAFETY] Checking broker for open positions on startup...")
            open_positions = {k: v for k, v in self.broker.positions.items() if v.get('qty', 0) != 0}
            if open_positions:
                logger.warning(f"[SAFETY] Found {len(open_positions)} open positions at startup - rebuilding leg state")
                # Use get() with lock to safely access state dict from strategy engine context
                state_dict = self.state.get('trade_state', {}) or {}
                recovered_state = self.safety_validator.rebuild_leg_state_from_broker(open_positions, state_dict)
                # Apply recovered state
                if recovered_state != state_dict:
                    self.state.update(recovered_state)
            else:
                logger.info("[SAFETY] No open positions at broker - starting fresh")
        except Exception:
            logger.exception("[SAFETY] Restart recovery error")

        # STANDBY MODE: Subscribe to spot immediately for pre-market heartbeat
        try:
            self._enter_standby_mode()
        except Exception:
            logger.exception("Standby mode setup failed")

        # resubscribe tokens if needed
        try:
            self._resubscribe_on_restart()
        except Exception:
            logger.exception("Resubscribe on restart failed")

        # start monitors
        self._stop_event.clear()
        self.threads = [
            threading.Thread(target=self._phase_monitor, daemon=True),
            threading.Thread(target=self._entry_monitor, daemon=True),
            threading.Thread(target=self._exit_monitor, daemon=True),
            threading.Thread(target=self._squareoff_monitor, daemon=True),
            threading.Thread(target=self._heartbeat_loop, daemon=True),
            threading.Thread(target=self._trailing_observation_monitor, daemon=True)  # New: Trailing SL observer
        ]
        for t in self.threads:
            t.start()

        # start replay if applicable (UnifiedFeed handles this in many setups)
        if Config.DATA_MODE == "REPLAY":
            try:
                self.feed.start_replay()
            except Exception:
                logger.exception("Failed to start replay")

        logger.info("[OK] Strategy engine started")

    def stop(self):
        logger.info("[STOP] Stopping strategy engine...")
        self._stop_event.set()
        for t in self.threads:
            try:
                t.join(timeout=2)
            except Exception:
                pass
        try:
            self.feed.close()
        except Exception:
            pass
        logger.info("[STOP] Strategy engine stopped")

    # -------------------------
    # unified tick handler
    # -------------------------
    
    def _on_tick(self, token, symbol, ltp, timestamp, delta=None):
        # Update InstrumentMaster with every tick
        self.instruments.update_snapshot(token, ltp, delta)
        
        # Original day change logic
        if token == 'DAY_CHANGE':
            self._handle_day_change(timestamp)

    
    # ... (rest of file)
    def _handle_day_change(self, ts):
        try:
            date_str = ts if isinstance(ts, str) else getattr(ts, 'isoformat', lambda: str(ts))()
            logger.info(f" Day change detected: {date_str}")
            
            # Reset daily flags
            self.state.update({
                'phase0_done': False,
                'phase1_done': False
            })
            
            # Reset PhaseManager state for new trading day
            self.phase_manager.reset()
            self.set_phase(PHASE_INIT)
            
            # Notify strikes cleared
            if self.notifier:
                try:
                    self.notifier.send_trade_log(f"Day change: {date_str} - resetting daily state")
                except Exception:
                    logger.exception("Notifier send_trade_log failed")
        except Exception:
            logger.exception("Error handling day change")

    # -------------------------
    # Phase management
    # -------------------------
    def set_phase(self, new_phase: str) -> None:
        """
        CRITICAL: Central phase transition function.
        
        Validates phase against constants, writes atomically to state,
        and invokes notifier phase change callback.
        
        Args:
            new_phase: New phase string (must be one of PHASE_* constants)
            
        Raises:
            ValueError: If phase is not a recognized constant
        """
        # Validate phase against known constants
        valid_phases = [PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1, PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED]
        if new_phase not in valid_phases:
            logger.error(f"[ERROR] INVALID PHASE: {new_phase} (must be one of {valid_phases})")
            raise ValueError(f"Invalid phase: {new_phase}")
        
        # Get current phase for logging
        current_phase = self.state.get('phase')
        
        # Only log if actually changing
        if current_phase != new_phase:
            logger.info(f"[PHASE] PHASE TRANSITION: {current_phase} -> {new_phase}")
            
            # Write phase atomically to state
            self.state.set('phase', new_phase)
            
            # Notify about phase change
            if self.notifier:
                try:
                    self.notifier.send_phase_change(new_phase)
                except Exception as e:
                    logger.warning(f"[WARN] Failed to notify phase change: {e}")
    
    # -------------------------
    # Stop-loss modification (with retry and confirmation)
    # -------------------------
    def _modify_sl_with_retry(self, order_id: str, new_sl: float, leg_key: str) -> bool:
        """
        Safely modify stop-loss for a leg with retry logic and cooldown.
        
        CRITICAL: Used for trailing SL updates to ensure broker confirms change.
        - Cooldown: 30 seconds between SL updates per leg to avoid broker throttling
        - Retries: Up to 2 attempts if broker responds with error
        - Confirmation: Only update internal SL on broker success
        - Escalation: Alert notifier if persistent failures occur
        
        Args:
            order_id: Broker order ID
            new_sl: New stop-loss price
            leg_key: Leg identifier for cooldown tracking ('sell_ce', 'sell_pe', etc.)
            
        Returns:
            bool: True if modification confirmed, False if failed
        """
        SL_COOLDOWN_SECONDS = 30.0
        SL_MODIFY_MAX_RETRIES = 2
        
        # Check cooldown to prevent broker throttling
        last_modify_key = f'_last_sl_modify_{leg_key}'
        last_modify_time = self.state.get(last_modify_key)
        
        if last_modify_time:
            elapsed = time.time() - last_modify_time
            if elapsed < SL_COOLDOWN_SECONDS:
                remaining = SL_COOLDOWN_SECONDS - elapsed
                logger.debug(f" SL cooldown active for {leg_key}: {remaining:.1f}s remaining")
                return False
        
        # Attempt to modify with retries
        for attempt in range(1, SL_MODIFY_MAX_RETRIES + 1):
            try:
                logger.info(f" Modifying SL for {leg_key} (attempt {attempt}/{SL_MODIFY_MAX_RETRIES}): Rs{new_sl:.2f}")
                
                # Call broker modify_order if available
                if hasattr(self.broker, 'modify_order') and callable(self.broker.modify_order):
                    response = self.broker.modify_order(
                        order_id=order_id,
                        trigger_price=new_sl
                    )
                    
                    # Check response success
                    if response and response.get('status') in ['SUCCESS', 'MODIFIED', 'FILLED']:
                        # Success: update internal SL and cooldown timestamp
                        logger.info(f"[OK] SL modified successfully for {leg_key}: Rs{new_sl:.2f}")
                        self.state.set(last_modify_key, time.time())
                        
                        # Update internal SL state
                        self.state.set(f'{leg_key}_sl', new_sl)
                        
                        # Send success notification
                        if self.notifier:
                            try:
                                strike = self.state.get(f'{leg_key}_strike', 0)
                                self.notifier.send_trailing_sl_update_success(leg_key, new_sl, strike)
                            except Exception:
                                pass
                        
                        return True
                    else:
                        logger.warning(f"[WARN] SL modify failed (attempt {attempt}): {response}")
                else:
                    # Broker doesn't support modify_order - skip
                    logger.debug(f" Broker doesn't support modify_order, skipping SL modification")
                    return False
                
            except Exception as e:
                logger.warning(f"[WARN] SL modify exception (attempt {attempt}): {e}")
                
                # Last attempt failed - escalate to notifier
                if attempt == SL_MODIFY_MAX_RETRIES:
                    logger.error(f"[ERROR] SL MODIFICATION FAILED for {leg_key} after {SL_MODIFY_MAX_RETRIES} attempts")
                    
                    if self.notifier:
                        try:
                            strike = self.state.get(f'{leg_key}_strike', 0)
                            self.notifier.send_trade_log(
                                f"[WARN] SL MODIFY FAILED\n"
                                f"Leg: {leg_key.upper()}\n"
                                f"Target SL: Rs{new_sl:.2f}\n"
                                f"Manual intervention may be required"
                            )
                        except Exception:
                            pass
                    
                    return False
                else:
                    # Retry after a short delay
                    time.sleep(1)
        
        return False

    # -------------------------
    # LTP unavailability helpers
    # -------------------------
    def _track_token_subscription(self, tokens):
        """
        Internal helper: Record subscription time for tokens to enable first-tick grace period.
        This prevents premature LTP unavailable warnings during WebSocket tick latency.
        
        Args:
            tokens: List of tokens or single token being subscribed
        """
        current_time = time.time()
        if not isinstance(tokens, (list, tuple)):
            tokens = [tokens]
        for token in tokens:
            self._token_subscription_times[str(token)] = current_time
    
    def _should_skip_ltp_check(self, token):
        """
        Internal helper: Determine if LTP check should be skipped for this token.
        Returns True during first-tick grace period after subscription.
        
        Args:
            token: Token to check
            
        Returns:
            bool: True if check should be skipped (grace period active), False otherwise
        """
        token_str = str(token)
        subscription_time = self._token_subscription_times.get(token_str)
        
        # If we don't have a subscription time, allow the check
        if subscription_time is None:
            return False
        
        # Check if we're within the grace period
        elapsed = time.time() - subscription_time
        if elapsed < self._FIRST_TICK_GRACE_SECONDS:
            # Still in grace period - skip check silently
            return True
        
        return False
    
    def _should_log_ltp_warning(self, token):
        """
        Internal helper: Rate-limit LTP unavailable warnings per token.
        Prevents log spam by ensuring warnings are logged at most once per rate limit interval.
        
        Args:
            token: Token to check
            
        Returns:
            bool: True if warning should be logged, False if rate-limited
        """
        token_str = str(token)
        current_time = time.time()
        last_warning_time = self._last_warning_times.get(token_str)
        
        # If never warned before, allow it
        if last_warning_time is None:
            self._last_warning_times[token_str] = current_time
            return True
        
        # Check if enough time has elapsed since last warning
        elapsed = current_time - last_warning_time
        if elapsed >= self._WARNING_RATE_LIMIT_SECONDS:
            self._last_warning_times[token_str] = current_time
            return True
        
        return False

    # -------------------------
    # standby mode (pre-market)
    # -------------------------
    def _enter_standby_mode(self):
        """Subscribe to spot index immediately for pre-market heartbeat"""
        try:
            now = ist_now().time()
            if now < Config.PHASE0_START:
                logger.info("  STANDBY MODE: Market not open yet, subscribing to spot for heartbeat")
                spot = self.instruments.find_spot()
                if spot:
                    spot_token = spot['token']
                    try:
                        self.feed.subscribe(
                            [spot_token], 
                            {spot_token: spot.get('symbol', 'Nifty 50')}, 
                            Config.SPOT_EXCHANGE
                        )
                        self._track_token_subscription([spot_token])  # Track subscription time
                        self.state.set('phase', PHASE_STANDBY)
                        logger.info("[OK] Standby subscription active - WebSocket alive, waiting for market open")
                    except Exception as e:
                        # Suppress connection errors during standby - just log as info
                        logger.info(f"Standby: WebSocket connection pending - {e}")
            else:
                logger.info("Market hours detected - skipping standby mode")
        except Exception as e:
            logger.debug(f"Standby mode setup: {e}")

    # -------------------------
    # resubscribe helper
    # -------------------------
    def _resubscribe_on_restart(self):
        tokens = []
        symbols = {}
        # phase0 tokens
        if self.state.get('phase0_done'):
            for key in ('sell_ce_token', 'sell_pe_token'):
                tok = self.state.get(key)
                sym = self.state.get(key.replace('_token', '_symbol'))
                if tok:
                    tokens.append(tok)
                    symbols[str(tok)] = sym or f"Token-{tok}"
        # phase1 tokens
        if self.state.get('phase1_done'):
            for key in ('otm_ce_token', 'otm_pe_token'):
                tok = self.state.get(key)
                sym = self.state.get(key.replace('_token', '_symbol'))
                if tok:
                    tokens.append(tok)
                    symbols[str(tok)] = sym or f"Token-{tok}"
        if tokens:
            logger.info(f" Re-subscribing {len(tokens)} tokens")
            try:
                self.feed.subscribe(tokens, symbols, Config.EXCHANGE)
                time.sleep(1)
                if self.notifier:
                    try:
                        self.notifier.send_trade_log(f"Re-subscribed {len(tokens)} tokens")
                    except Exception:
                        pass
            except Exception:
                logger.exception("Resubscribe failed")

    # -------------------------
    # phase monitor and execution
    # -------------------------
    def _phase_monitor(self):
        while not self._stop_event.is_set():
            try:
                now = ist_now()
                ct = now.time()
                
                # STANDBY: Before market open
                if ct < Config.PHASE0_START:
                    if self.state.get('phase') != PHASE_STANDBY:
                        self.set_phase(PHASE_STANDBY)
                    time.sleep(1)
                    continue
                
                # PHASE 0: ITM Strike Selection
                if Config.PHASE0_START <= ct < Config.PHASE0_END:
                    if not self.state.get('phase0_done'):
                        if self.state.get('phase') != PHASE_PHASE0:
                            self.set_phase(PHASE_PHASE0)
                        self._execute_phase0()
                        time.sleep(1)  # CRITICAL: Throttle Phase 0 execution
                    else:
                        time.sleep(0.5)  # Phase 0 done, light throttle
                
                # PHASE 1: OTM Strike Selection (Independent)
                elif Config.PHASE1_START <= ct < Config.PHASE1_END:
                    if not self.state.get('phase1_done'):
                        if self.state.get('phase') != PHASE_PHASE1:
                            self.set_phase(PHASE_PHASE1)
                        self._execute_phase1()
                        # CRITICAL: Throttle Phase 1 execution - prevents infinite loop
                        # Phase 1 has internal retry logic, so sleep here prevents CPU burn
                        time.sleep(3)  # 3 second throttle between Phase 1 attempts
                    else:
                        time.sleep(0.5)  # Phase 1 done, light throttle
                
                # TRADING: Active trading phase
                elif ct >= Config.PHASE1_END and ct < Config.SQUAREOFF_TIME:
                    if self.state.get('phase') != PHASE_IN_TRADE:
                        self.set_phase(PHASE_IN_TRADE)
                    time.sleep(1)
                
                # CLOSED: Post square-off
                elif ct >= Config.SQUAREOFF_TIME:
                    if self.state.get('phase') != PHASE_CLOSED:
                        self.set_phase(PHASE_CLOSED)
                    time.sleep(1)
                else:
                    time.sleep(0.5)
                
            except Exception:
                logger.exception("Phase monitor error")
                time.sleep(1)

    def _execute_phase0(self):
        try:
            spot = self.instruments.find_spot()
            if not spot:
                logger.warning("PHASE0: Spot instrument not found")
                return
            spot_token = spot['token']
            self.feed.subscribe([spot_token], {spot_token: spot.get('symbol', 'Spot')}, Config.SPOT_EXCHANGE)
            self._track_token_subscription([spot_token])  # Track subscription time

            # wait for spot LTP
            spot_ltp = None
            for _ in range(10):
                spot_ltp = self.feed.get_ltp(spot_token)
                if spot_ltp:
                    break
                time.sleep(0.3)
            if not spot_ltp:
                logger.warning("PHASE0: Spot LTP unavailable")
                return

            atm = int((spot_ltp + Config.ATM_ROUND / 2) // Config.ATM_ROUND * Config.ATM_ROUND)
            sell_ce_strike = atm - Config.SELL_CE_OFFSET
            sell_pe_strike = atm + Config.SELL_PE_OFFSET

            expiry = self.instruments.get_nearest_expiry()
            if not expiry:
                logger.warning("PHASE0: No expiry found")
                return

            sell_ce = self.instruments.find_option(sell_ce_strike, 'CE', expiry)
            sell_pe = self.instruments.find_option(sell_pe_strike, 'PE', expiry)
            if not sell_ce or not sell_pe:
                logger.warning("PHASE0: Sell options not found")
                return

            # attempt to get lot size if available
            lot_size = 1
            try:
                lot_size = self.instruments.get_lot_size(sell_ce['token'])
            except Exception:
                pass

            # subscribe to option tokens
            self.feed.subscribe([sell_ce['token'], sell_pe['token']],
                                {sell_ce['token']: sell_ce['symbol'], sell_pe['token']: sell_pe['symbol']},
                                Config.EXCHANGE)
            self._track_token_subscription([sell_ce['token'], sell_pe['token']])  # Track subscription time
            
            # Wait for initial LTP before locking
            time.sleep(1)
            sell_ce_ltp = self.feed.get_ltp(sell_ce['token'])
            sell_pe_ltp = self.feed.get_ltp(sell_pe['token'])
            
            if not sell_ce_ltp or not sell_pe_ltp:
                logger.warning("PHASE0: Waiting for option LTP...")
                time.sleep(1)
                sell_ce_ltp = self.feed.get_ltp(sell_ce['token']) or 0
                sell_pe_ltp = self.feed.get_ltp(sell_pe['token']) or 0

            self.state.update({
                'spot_reference': spot_ltp,
                'atm_strike': atm,
                'expiry': expiry,
                'lot_size': lot_size,
                'sell_ce_strike': sell_ce_strike,
                'sell_pe_strike': sell_pe_strike,
                'phase0_done': True
            })
            
            # INDEPENDENT LEG LOCKING - SELL CE
            self.state.lock_sell_ce_leg({
                'token': sell_ce['token'],
                'strike': sell_ce_strike,
                'symbol': sell_ce['symbol'],
                'ltp': sell_ce_ltp
            })
            
            # INDEPENDENT LEG LOCKING - SELL PE
            self.state.lock_sell_pe_leg({
                'token': sell_pe['token'],
                'strike': sell_pe_strike,
                'symbol': sell_pe['symbol'],
                'ltp': sell_pe_ltp
            })

            logger.info(f"[OK] PHASE0: ATM={atm}, SELL CE={sell_ce_strike}, PE={sell_pe_strike}")
            if self.notifier:
                try:
                    self.notifier.send_trade_log(f"PHASE0 selected ATM={atm}, CE={sell_ce['symbol']}, PE={sell_pe['symbol']}")
                except Exception:
                    pass
        except Exception:
            logger.exception("PHASE0 failed")

    def _execute_phase1(self):
        """
        PHASE 1: FULLY INDEPENDENT BUY LEG SELECTION
        Runs independently - does not block SELL legs
        Uses delta-based selection with proper throttling
        
        CRITICAL: If BUY legs cannot be found, Phase 1 still completes
        to allow SELL legs to trade independently.
        """
        try:
            # FIX: Ensure phase1_done is set if we return early
            if self.state.get('buy_ce_leg_ready') and self.state.get('buy_pe_leg_ready'):
                if not self.state.get('phase1_done'):
                    self.state.set('phase1_done', True)
                    self.state.set('phase1_complete_time', time.time())
                    logger.info("[OK] PHASE1: Both BUY legs locked and ready")
                    
                    # Send lock event notification (all 4 legs ready)
                    if self.notifier:
                        try:
                            sell_ce_strike = self.state.get('sell_ce_strike', 0)
                            sell_ce_ref = self.state.get('sell_ce_ref_premium', 0.0)
                            sell_pe_strike = self.state.get('sell_pe_strike', 0)
                            sell_pe_ref = self.state.get('sell_pe_ref_premium', 0.0)
                            buy_ce_strike = self.state.get('buy_ce_strike', 0)
                            buy_ce_ref = self.state.get('buy_ce_ref_premium', 0.0)
                            buy_pe_strike = self.state.get('buy_pe_strike', 0)
                            buy_pe_ref = self.state.get('buy_pe_ref_premium', 0.0)
                            
                            self.notifier.send_lock_event(
                                sell_ce_strike, sell_ce_ref,
                                sell_pe_strike, sell_pe_ref,
                                buy_ce_strike, buy_ce_ref,
                                buy_pe_strike, buy_pe_ref
                            )
                        except Exception:
                            pass
                return
            
            # CRITICAL FIX: Track phase1 attempts to prevent infinite loop
            attempt_count = self.state.get('_phase1_attempt_count', 0)
            max_attempts = Config.PHASE1_MAX_ATTEMPTS  # Use Config value
            
            if attempt_count >= max_attempts:
                # Max attempts reached - mark phase1 done WITHOUT buy legs
                if not self.state.get('phase1_done'):
                    logger.warning(f"[WARN] PHASE1: Max attempts ({max_attempts}) reached - completing WITHOUT buy legs")
                    logger.warning("[WARN] SELL legs will trade independently without hedges")
                    self.state.set('phase1_done', True)
                    self.state.set('phase1_complete_time', time.time())
                    self.state.set('_phase1_completed_without_hedges', True)
                return
            
            # Increment attempt counter
            self.state.set('_phase1_attempt_count', attempt_count + 1)
            logger.info(f"PHASE1: Attempt {attempt_count + 1}/{max_attempts}")
            
            # Get ATM from Phase 0 OR calculate independently
            atm = self.state.get('atm_strike')
            if not atm:
                # Phase 0 hasn't run - calculate ATM ourselves
                logger.info("PHASE1: Phase 0 not completed, calculating independent ATM")
                spot = self.instruments.find_spot()
                if spot:
                    spot_ltp = self.feed.get_ltp(spot['token'])
                    if spot_ltp and spot_ltp > 0:
                        atm = int((spot_ltp + Config.ATM_ROUND / 2) // Config.ATM_ROUND * Config.ATM_ROUND)
                        logger.info(f"PHASE1: Calculated independent ATM={atm} from spot={spot_ltp:.2f}")
                    else:
                        logger.warning("PHASE1: Cannot get spot LTP, will retry next attempt...")
                        time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE: Wait before next attempt
                        return
                else:
                    logger.warning("PHASE1: Cannot find spot instrument")
                    time.sleep(2)
                    return
            
            # Get expiry independently
            expiry = self.state.get('expiry')
            if not expiry:
                expiry = self.instruments.get_nearest_expiry()
                if expiry:
                    logger.info(f"PHASE1: Using independently fetched expiry={expiry}")
                else:
                    logger.warning("PHASE1: Cannot determine expiry, will retry next attempt...")
                    time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt
                    return
            
            # Define Range
            range_val = Config.DELTA_SCAN_RANGE * Config.ATM_ROUND
            
            # FIX: Only fetch and subscribe to options if that specific leg is NOT locked
            ce_options = []
            if not self.state.get('buy_ce_leg_ready'):
                ce_options = self.instruments.find_options_in_range(atm, atm + range_val, 'CE', expiry)
                
            pe_options = []
            if not self.state.get('buy_pe_leg_ready'):
                pe_options = self.instruments.find_options_in_range(atm - range_val, atm, 'PE', expiry)
            
            # Subscribe to options for delta calculation
            if ce_options or pe_options:
                tokens_to_subscribe = []
                symbol_map = {}
                for opt in ce_options + pe_options:
                    token = opt['token']
                    tokens_to_subscribe.append(token)
                    symbol_map[token] = opt['symbol']
                
                if tokens_to_subscribe:
                    try:
                        logger.info(f"PHASE1: Subscribing to {len(tokens_to_subscribe)} options for delta calculation")
                        self.feed.subscribe(tokens_to_subscribe, symbol_map, Config.EXCHANGE)
                        self._track_token_subscription(tokens_to_subscribe)  # Track subscription time
                        
                        # CRITICAL FIX: Wait with proper throttling
                        logger.info("PHASE1: Waiting for ticks and delta calculation...")
                        max_wait_seconds = Config.PHASE1_DATA_WAIT_SECONDS
                        wait_iterations = int(max_wait_seconds / Config.PHASE1_DATA_CHECK_INTERVAL)
                        
                        for i in range(wait_iterations):
                            # REQUIREMENT 7: DELTA SELECTION LOOP SAFETY - Check timeout and retry limits
                            elapsed_time = (i + 1) * Config.PHASE1_DATA_CHECK_INTERVAL
                            should_continue, safety_msg = self.safety_validator.validate_delta_loop_safety(
                                attempt_number=attempt_count,
                                max_retries=Config.DELTA_LOOP_MAX_RETRIES,
                                elapsed_time=elapsed_time,
                                timeout_seconds=Config.DELTA_LOOP_TIMEOUT
                            )
                            
                            if not should_continue:
                                logger.warning(f"PHASE1: Delta loop safety limit reached: {safety_msg}")
                                time.sleep(Config.PHASE1_RETRY_DELAY)
                                return
                            
                            time.sleep(Config.PHASE1_DATA_CHECK_INTERVAL)  # THROTTLE: Check interval
                            
                            # Check valid deltas
                            valid_deltas = 0
                            for token in tokens_to_subscribe:
                                snap = self.instruments.get_snapshot(token)
                                if snap.get('delta') is not None:
                                    valid_deltas += 1
                            
                            # Proceed when 50% ready
                            if valid_deltas > len(tokens_to_subscribe) * 0.5:
                                elapsed = (i+1) * Config.PHASE1_DATA_CHECK_INTERVAL
                                logger.info(f"PHASE1: [OK] Sufficient data received ({valid_deltas}/{len(tokens_to_subscribe)} options ready after {elapsed:.1f}s)")
                                break
                            
                            if (i + 1) % 4 == 0:  # Log every few iterations
                                elapsed = (i+1) * Config.PHASE1_DATA_CHECK_INTERVAL
                                logger.info(f"PHASE1: Waiting for data... ({valid_deltas}/{len(tokens_to_subscribe)} ready, {elapsed:.1f}s elapsed)")
                        else:
                            logger.warning(f"PHASE1: Timeout after {max_wait_seconds}s - only {valid_deltas}/{len(tokens_to_subscribe)} options have valid delta")
                            logger.warning(f"PHASE1: Will retry (attempt {attempt_count + 1}/{max_attempts})")
                            time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt
                            return
                        
                    except Exception as e:
                        logger.warning(f"PHASE1: Failed to subscribe: {e}")
                        time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt
                        return
            
            # PHASE 1 FIX: Per-leg attempt tracking for independent leg processing
            # Each leg now tracks its own attempt counter
            ce_attempts = self.state.get('_phase1_buy_ce_attempts', 0)
            pe_attempts = self.state.get('_phase1_buy_pe_attempts', 0)
            max_per_leg = Config.PHASE1_MAX_ATTEMPTS_PER_LEG if hasattr(Config, 'PHASE1_MAX_ATTEMPTS_PER_LEG') else 30
            
            ce_exhausted = ce_attempts >= max_per_leg
            pe_exhausted = pe_attempts >= max_per_leg
            
            # Select BUY CE leg independently (with per-leg attempt tracking)
            if not self.state.get('buy_ce_leg_ready'):
                if not ce_exhausted:
                    buy_ce = self._select_by_delta(atm, atm + range_val, 'CE', expiry, Config.TARGET_CE_DELTA)
                    if buy_ce:
                        self.state.lock_buy_ce_leg(buy_ce)
                        logger.info(f"[OK] PHASE1: BUY CE locked at strike {buy_ce.get('strike')}")
                    else:
                        logger.warning(f"PHASE1: BUY CE not found (attempt {ce_attempts + 1}/{max_per_leg})")
                        self.state.set('_phase1_buy_ce_attempts', ce_attempts + 1)
                        time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt
                else:
                    logger.warning(f"PHASE1: BUY CE max attempts ({max_per_leg}) exhausted - stopping CE retries")
                    self.state.set('_phase1_buy_ce_final_status', 'FAILED_MAX_ATTEMPTS')
            
            # Select BUY PE leg independently (with per-leg attempt tracking)
            if not self.state.get('buy_pe_leg_ready'):
                if not pe_exhausted:
                    buy_pe = self._select_by_delta(atm - range_val, atm, 'PE', expiry, Config.TARGET_PE_DELTA)
                    if buy_pe:
                        self.state.lock_buy_pe_leg(buy_pe)
                        logger.info(f"[OK] PHASE1: BUY PE locked at strike {buy_pe.get('strike')}")
                    else:
                        logger.warning(f"PHASE1: BUY PE not found (attempt {pe_attempts + 1}/{max_per_leg})")
                        self.state.set('_phase1_buy_pe_attempts', pe_attempts + 1)
                        time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt
                else:
                    logger.warning(f"PHASE1: BUY PE max attempts ({max_per_leg}) exhausted - stopping PE retries")
                    self.state.set('_phase1_buy_pe_final_status', 'FAILED_MAX_ATTEMPTS')
            
            # IMPROVED GATE: Mark phase1_done when:
            # 1. Both legs ready (success), OR
            # 2. Both legs exhausted (give up), OR
            # 3. Global attempt limit exceeded (safety)
            both_legs_ready = (self.state.get('buy_ce_leg_ready') and self.state.get('buy_pe_leg_ready'))
            both_legs_exhausted = (ce_exhausted and pe_exhausted)
            
            if both_legs_ready:
                # Both legs locked successfully
                self.state.set('phase1_done', True)
                self.state.set('phase1_complete_time', time.time())
                logger.info("[OK] PHASE1: Both BUY legs locked and ready")
                
                # Send lock event notification (all 4 legs ready)
                if self.notifier:
                    try:
                        sell_ce_strike = self.state.get('sell_ce_strike', 0)
                        sell_ce_ref = self.state.get('sell_ce_ref_premium', 0.0)
                        sell_pe_strike = self.state.get('sell_pe_strike', 0)
                        sell_pe_ref = self.state.get('sell_pe_ref_premium', 0.0)
                        buy_ce_strike = self.state.get('buy_ce_strike', 0)
                        buy_ce_ref = self.state.get('buy_ce_ref_premium', 0.0)
                        buy_pe_strike = self.state.get('buy_pe_strike', 0)
                        buy_pe_ref = self.state.get('buy_pe_ref_premium', 0.0)
                        
                        self.notifier.send_lock_event(
                            sell_ce_strike, sell_ce_ref,
                            sell_pe_strike, sell_pe_ref,
                            buy_ce_strike, buy_ce_ref,
                            buy_pe_strike, buy_pe_ref
                        )
                    except Exception:
                        pass
            
            elif both_legs_exhausted:
                # Both legs exhausted max attempts - complete with partial/no hedges
                self.state.set('phase1_done', True)
                self.state.set('phase1_complete_time', time.time())
                self.state.set('_phase1_completed_without_hedges', True)
                
                ce_status = self.state.get('_phase1_buy_ce_final_status', 'UNKNOWN')
                pe_status = self.state.get('_phase1_buy_pe_final_status', 'UNKNOWN')
                
                logger.warning("[WARN] PHASE1: Both legs exhausted max attempts - completing phase1")
                logger.warning(f"  BUY CE leg status: {ce_status} (ready={self.state.get('buy_ce_leg_ready', False)})")
                logger.warning(f"  BUY PE leg status: {pe_status} (ready={self.state.get('buy_pe_leg_ready', False)})")
                logger.warning("[WARN] PHASE1: Entry monitor will work with available hedges")
            
            elif attempt_count >= max_attempts:
                # Global attempt limit exceeded (safety net for old logic)
                self.state.set('phase1_done', True)
                self.state.set('phase1_complete_time', time.time())
                self.state.set('_phase1_completed_without_hedges', True)
                
                logger.warning(f"[WARN] PHASE1: Global attempt limit ({max_attempts}) exceeded - forcing phase1_done")
                logger.warning(f"  BUY CE: ready={self.state.get('buy_ce_leg_ready', False)}, attempts={ce_attempts}")
                logger.warning(f"  BUY PE: ready={self.state.get('buy_pe_leg_ready', False)}, attempts={pe_attempts}")

        except Exception:
            logger.exception("PHASE1 Delta Selection failed")
            time.sleep(Config.PHASE1_RETRY_DELAY)  # THROTTLE before next attempt

    def _select_by_delta(self, min_strike, max_strike, opt_type, expiry, target_delta):
        options = self.instruments.find_options_in_range(min_strike, max_strike, opt_type, expiry)
        best_option = None
        min_score = float('inf')

        for opt in options:
            token = opt['token']
            snap = self.instruments.get_snapshot(token)
            ltp = snap['ltp']
            delta = snap['delta']

            if delta is not None and ltp > 0:
                score = abs(delta - target_delta)
                if score < min_score:
                    min_score = score
                    best_option = {
                        'token': token,
                        'symbol': opt['symbol'],
                        'strike': int(float(opt['strike'])) // 100,
                        'delta': delta,
                        'ltp': ltp
                    }
        return best_option

    # -------------------------
    # entry / exit monitors
    # -------------------------
    def _entry_monitor(self):
        """
        FULLY INDEPENDENT LEG MONITORING
        Each leg (SELL CE, SELL PE, BUY CE, BUY PE) checks and enters independently
        """
        while not self._stop_event.is_set():
            try:
                # REQUIREMENT 1: BROKER POSITION RECONCILIATION (throttled to 30s)
                # Force a fresh reconciliation from broker API before making decisions
                try:
                    if hasattr(self.broker, '_sync_positions_from_broker'):
                        self.broker._sync_positions_from_broker()
                    else:
                        # Fallback to fetch API if sync method missing
                        if hasattr(self.broker, 'fetch_positions_from_broker'):
                            self.broker.fetch_positions_from_broker()
                except Exception:
                    logger.exception("Failed to force reconciliation before strategy decision - blocking entries")
                    try:
                        self.state.set('trading_blocked_reconcile_stale', True)
                    except Exception:
                        logger.exception("Failed to persist trading_blocked_reconcile_stale flag")
                    time.sleep(5)
                    continue

                reconciled, recon_msg = self.safety_validator.validate_broker_positions(
                    self.state.get('trade_state', {}) or {},
                    self.broker.positions,
                    threshold_seconds=30
                )
                if not reconciled:
                    logger.error(f"[SAFETY] Position mismatch detected - blocking new entries: {recon_msg}")
                    time.sleep(5)  # Wait before retrying reconciliation check
                    continue
                
                # Check hard exit before processing entries
                if self._check_hard_exit():
                    # Hard exit triggered - sleep and check again periodically
                    time.sleep(1)
                    continue
                
                # Check if hard exit blocks new entries
                if self.state.get('hard_exit_no_new_entries'):
                    logger.warning(" Hard exit: new entries disabled - skipping entry monitor")
                    time.sleep(1)
                    continue

                # Persistent hard-exit block (manual reset required)
                if self.state.get('hard_exit_blocked'):
                    logger.critical(" Hard-exit BLOCK: trading blocked until manual reset - skipping entry monitor")
                    time.sleep(5)
                    continue
                
                # REQUIREMENT 4: CE AND PE LEG INDEPENDENCE VERIFICATION
                legs_valid, legs_msg = self.safety_validator.verify_leg_independence(
                    self.state.state if hasattr(self.state, 'state') else {}
                )
                if not legs_valid:
                    logger.error(f"[SAFETY] Leg independence violation: {legs_msg}")
                    time.sleep(5)
                    continue
                
                # Reset trade entry flag when starting fresh trade
                if (self.state.get('sell_ce_leg_ready') and self.state.get('sell_pe_leg_ready') and
                    not self.state.get('sell_ce_entered') and not self.state.get('sell_pe_entered')):
                    if self.notifier:
                        try:
                            self.notifier.state_cache.reset_trade_entry_flag()
                        except Exception:
                            pass
                
                # SELL CE - Independent execution
                if self.state.get('sell_ce_leg_ready') and not self.state.get('sell_ce_entered'):
                    self._check_sell_entry('ce')
                
                # SELL PE - Independent execution
                if self.state.get('sell_pe_leg_ready') and not self.state.get('sell_pe_entered'):
                    self._check_sell_entry('pe')
                
                # Check if both SELL legs entered and send trade entry notification
                if (self.state.get('sell_ce_entered') and self.state.get('sell_pe_entered') and
                    self.notifier):
                    try:
                        sell_ce_strike = self.state.get('sell_ce_strike', 0)
                        sell_ce_price = self.state.get('sell_ce_entry_price', 0.0)
                        sell_ce_sl = sell_ce_price * (1 + Config.SELL_SL_PERCENT)
                        
                        sell_pe_strike = self.state.get('sell_pe_strike', 0)
                        sell_pe_price = self.state.get('sell_pe_entry_price', 0.0)
                        sell_pe_sl = sell_pe_price * (1 + Config.SELL_SL_PERCENT)
                        
                        self.notifier.send_trade_entry(
                            sell_ce_strike, sell_ce_price, sell_ce_sl,
                            sell_pe_strike, sell_pe_price, sell_pe_sl
                        )
                    except Exception:
                        pass
                
                # BUY CE - Independent execution (only if leg is ready)
                if self.state.get('buy_ce_leg_ready') and not self.state.get('buy_ce_entered'):
                    self._check_buy_entry('ce')
                
                # BUY PE - Independent execution (only if leg is ready)
                if self.state.get('buy_pe_leg_ready') and not self.state.get('buy_pe_entered'):
                    self._check_buy_entry('pe')
                
            except Exception:
                logger.exception("Entry monitor error")
            
            # Enforce minimum iteration interval
            self._enforce_iteration_interval()

    def _check_sell_entry(self, ot):
        """Check and execute SELL entry with comprehensive debug logging"""
        try:
            if Config.DEBUG_MODE:
                logger.debug(f"[SELL_ENTRY_CHECK] Starting check for {ot.upper()}")
            if self.state.get(f'sell_{ot}_entered'):
                if Config.DEBUG_MODE:
                    logger.debug(f"[SELL_ENTRY_CHECK] {ot.upper()} already entered, skipping")
                return
            tok = self.state.get(f'sell_{ot}_token')
            ref = self.state.get(f'sell_{ot}_ref_premium')
            if Config.DEBUG_MODE:
                logger.debug(f"[SELL_ENTRY_CHECK] {ot.upper()} token={tok}, ref_premium={ref}")
            if not tok or ref is None:
                if Config.DEBUG_MODE:
                    logger.debug(f"[SELL_ENTRY_CHECK] {ot.upper()} missing token or ref_premium")
                return
            
            # FIX: Bypass strict 5-second freshness to ensure triggers evaluate reliably
            ltp = self.feed.get_ltp(tok, check_freshness=False)
            
            if Config.DEBUG_MODE:
                logger.debug(f"[SELL_ENTRY_CHECK] {ot.upper()} ltp={ltp}")
            if ltp is None:
                # Check if we should skip during grace period (newly subscribed token)
                if self._should_skip_ltp_check(tok):
                    # Silently skip - token is newly subscribed, waiting for first tick
                    return
                
                # Rate-limit warning logs to prevent spam
                if self._should_log_ltp_warning(tok):
                    logger.warning(f"[SELL_ENTRY_CHECK] {ot.upper()} LTP unavailable for token={tok}")
                return
            decay = ref - ltp
            trigger = Config.SELL_DECAY_TRIGGER
            condition_met = decay >= trigger
            logger.info(f"[SELL_ENTRY_CHECK] {ot.upper()} ref={ref:.2f}, ltp={ltp:.2f}, decay={decay:.2f}, trigger={trigger:.2f}, condition_met={condition_met}, broker_mode={Config.TRADING_MODE}")
            if condition_met:
                qty = Config.LOTS * self.state.get('lot_size', 1)
                label = f"SELL_{ot.upper()}_ENTRY"
                logger.info(f"[SELL_ENTRY_CHECK] [OK] CONDITION MET - Placing order: side=SELL, token={tok}, qty={qty}, price={ltp:.2f}")
                result = self._place_order_safe("SELL", tok, qty, ltp, label)
                if not result:
                    logger.error(f"[SELL_ENTRY_CHECK] [ERROR] Order failed (no result)")
                    return

                # Require explicit FILLED confirmation before marking entered
                status = result.get('status', '').upper() if isinstance(result, dict) else None
                if status != 'FILLED':
                    logger.error(f"[SELL_ENTRY_CHECK] [ERROR] Order not filled (status={status}) - aborting entry")
                    return

                logger.info(f"[SELL_ENTRY_CHECK] [OK] Order FILLED: {result}")
                self.state.update({f'sell_{ot}_entered': True, f'sell_{ot}_entry_price': ltp})
                logger.info(f" SELL {ot.upper()} @ Rs{ltp:.2f} - STATE UPDATED")
                
                # REQUIREMENT 2: STOP-LOSS ORDER VERIFICATION AFTER ENTRY
                # Verify SL order exists at broker (if applicable for this broker type)
                if hasattr(self.broker, 'orders'):
                    sl_verified = self.safety_validator.verify_sl_order_after_entry(
                        state=self.state.get('trade_state', {}) or {},
                        broker_orders=self.broker.orders,
                        entry_token=tok,
                        leg_key=f'sell_{ot}'
                    )
                    if not sl_verified:
                        logger.warning(f"[SAFETY] SL order verification failed for SELL_{ot.upper()} - will retry on next cycle")
                        # Do not mark as failed - SL may be created asynchronously
                
                if self.notifier:
                    try:
                        # FIX: Pass all leg details so Notifier tracks the leg for snapshots
                        self.notifier.send_entry(
                            label=f" SELL {ot.upper()}",
                            price=ltp,
                            token=tok,
                            strike=self.state.get(f'sell_{ot}_strike'),
                            option_type=ot.upper(),
                            qty=-qty,  # Negative qty for SELL leg
                            sl=ltp * (1 + Config.SELL_SL_PERCENT)
                        )
                    except Exception:
                        pass
        except Exception:
            logger.exception(f"_check_sell_entry error for {ot}")

    def _check_buy_entry(self, ot):
        """Check and execute BUY entry - FULLY INDEPENDENT of SELL"""
        try:
            if Config.DEBUG_MODE:
                logger.debug(f"[BUY_ENTRY_CHECK] Starting check for {ot.upper()}")
            if self.state.get(f'buy_{ot}_entered'):
                if Config.DEBUG_MODE:
                    logger.debug(f"[BUY_ENTRY_CHECK] {ot.upper()} already entered, skipping")
                return
            
            # Use new independent token names
            tok = self.state.get(f'buy_{ot}_token')
            ref = self.state.get(f'buy_{ot}_ref_premium')
            
            if Config.DEBUG_MODE:
                logger.debug(f"[BUY_ENTRY_CHECK] {ot.upper()} token={tok}, ref_premium={ref}")
            if not tok or ref is None:
                if Config.DEBUG_MODE:
                    logger.debug(f"[BUY_ENTRY_CHECK] {ot.upper()} missing token or ref_premium")
                return
            
            # FIX: Bypass strict 5-second freshness to ensure triggers evaluate reliably
            ltp = self.feed.get_ltp(tok, check_freshness=False)
            
            if Config.DEBUG_MODE:
                logger.debug(f"[BUY_ENTRY_CHECK] {ot.upper()} ltp={ltp}")
            if ltp is None:
                # Check if we should skip during grace period (newly subscribed token)
                if self._should_skip_ltp_check(tok):
                    # Silently skip - token is newly subscribed, waiting for first tick
                    return
                
                # Rate-limit warning logs to prevent spam
                if self._should_log_ltp_warning(tok):
                    logger.warning(f"[BUY_ENTRY_CHECK] {ot.upper()} LTP unavailable for token={tok}")
                return
            
            trig = (ref * Config.BUY_TRIGGER_MULTIPLIER) + Config.BUY_TRIGGER_ABSOLUTE
            condition_met = ltp >= trig
            logger.info(f"[BUY_ENTRY_CHECK] {ot.upper()} ref={ref:.2f}, ltp={ltp:.2f}, trigger={trig:.2f}, condition_met={condition_met}, broker_mode={Config.TRADING_MODE}")
            
            if condition_met:
                qty = Config.LOTS * self.state.get('lot_size', 1)
                label = f"BUY_{ot.upper()}_ENTRY"
                logger.info(f"[BUY_ENTRY_CHECK] [OK] CONDITION MET - Placing order: side=BUY, token={tok}, qty={qty}, price={ltp:.2f}")
                result = self._place_order_safe("BUY", tok, qty, ltp, label)
                if not result:
                    logger.error(f"[BUY_ENTRY_CHECK] [ERROR] Order failed (no result)")
                    return

                status = result.get('status', '').upper() if isinstance(result, dict) else None
                if status != 'FILLED':
                    logger.error(f"[BUY_ENTRY_CHECK] [ERROR] Order not filled (status={status}) - aborting entry")
                    return

                logger.info(f"[BUY_ENTRY_CHECK] [OK] Order FILLED: {result}")
                self.state.update({f'buy_{ot}_entered': True, f'buy_{ot}_entry_price': ltp})
                logger.info(f" BUY {ot.upper()} @ Rs{ltp:.2f} - STATE UPDATED")
                if self.notifier:
                    try:
                        # FIX: Pass all leg details so Notifier tracks the leg for snapshots
                        self.notifier.send_entry(
                            label=f" BUY {ot.upper()}",
                            price=ltp,
                            token=tok,
                            strike=self.state.get(f'buy_{ot}_strike'),
                            option_type=ot.upper(),
                            qty=qty,  # Positive qty for BUY leg
                            sl=ltp - Config.BUY_SL_POINTS
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.exception(f"_check_buy_entry error for {ot}: {e}")

    def _exit_monitor(self):
        while not self._stop_event.is_set():
            try:
                # Check hard exit first
                self._check_hard_exit()
                
                if self.state.get('phase') != PHASE_IN_TRADE:
                    time.sleep(0.2)
                    continue
                self._check_sell_exit('ce')
                self._check_sell_exit('pe')
                self._check_buy_exit('ce')
                self._check_buy_exit('pe')
            except Exception:
                logger.exception("Exit monitor error")
            
            # Enforce minimum iteration interval
            self._enforce_iteration_interval()

    def _check_sell_exit(self, ot):
        """
        Enhanced SELL exit logic with trailing stop-loss support.
        
        STRICT TIME-BASED BEHAVIOR ENFORCEMENT:
        1. Before 14:15: ONLY fixed SL/TP (no trailing calculation/reference)
        2. 14:00-14:15: EXPLICIT NEUTRAL GAP (hard-blocked from trailing)
        3. 14:15+: Trailing SL applies ONLY if it tightens risk
        
        CRITICAL FIXES:
        - Gap 1: Observation and decision logic are structurally separated
        - Gap 2: 14:00-14:15 neutral gap is hard-blocked with explicit guard
        - Gap 3: Exceptional condition (LTP >= adverse) is explicitly handled
        """
        try:
            if not self.state.get(f'sell_{ot}_entered') or self.state.get(f'sell_{ot}_exited'):
                return
            
            tok = self.state.get(f'sell_{ot}_token')
            entry = self.state.get(f'sell_{ot}_entry_price')
            if not tok or entry is None:
                return
            
            # FIX: Bypass strict 5-second freshness to ensure triggers evaluate reliably
            ltp = self.feed.get_ltp(tok, check_freshness=False)
            if ltp is None:
                return
            
            # ===== EXISTING FIXED SL/TP CALCULATION (ALWAYS PERFORMED) =====
            fixed_sl = entry * (1 + Config.SELL_SL_PERCENT)
            tp = entry * (1 - Config.SELL_TP_PERCENT)
            
            # Start with fixed SL as default
            sl = fixed_sl
            
            # ===== TIME-GATED TRAILING LOGIC (STRICTLY SEPARATED) =====
            current_time = ist_now().time()
            
            # ===== HARD BLOCK: NEUTRAL GAP WINDOW (14:00 - 14:15) =====
            # EXPLICIT PROHIBITION: No trailing calculation, reference, or evaluation
            if Config.TRAILING_OBSERVATION_END <= current_time < Config.TRAILING_ACTIVATION_TIME:
                # NEUTRAL GAP: Use ONLY fixed SL, do not even read trailing variables
                # This explicit guard enforces the dead-zone requirement
                pass  # Explicitly doing nothing - using fixed_sl already assigned above
            
            # ===== TRAILING ACTIVATION: FROM 14:15 ONWARDS ONLY =====
            elif current_time >= Config.TRAILING_ACTIVATION_TIME:
                # STRUCTURAL SEPARATION: Trailing decision logic is ONLY executed here
                # This is completely isolated from observation logic
                try:
                    # Read frozen adverse price (set during 12:00-14:00 observation)
                    with self._trailing_lock:
                        if ot == 'ce':
                            adverse_price = self._trailing_sell_ce_adverse_price
                        else:  # pe
                            adverse_price = self._trailing_sell_pe_adverse_price
                    
                    # Only proceed if we have a tracked adverse price
                    if adverse_price is not None:
                        # ===== EXCEPTIONAL CONDITION HANDLING (MANDATORY) =====
                        # If current LTP >= stored adverse price, we must handle this explicitly
                        if ltp >= adverse_price:
                            # CASE: Market already worse than stored reference
                            # MANDATORY ACTION: Align SL to current market + buffer
                            
                            # Calculate SL based on CURRENT price (not stored adverse)
                            current_based_sl = ltp * (1 + Config.TRAILING_BUFFER_PERCENT)
                            
                            # Use the tighter of: current-based SL or fixed SL
                            # (Never loosen beyond fixed SL)
                            if current_based_sl < fixed_sl:
                                sl = current_based_sl
                                logger.warning(
                                    f"[WARN] EXCEPTIONAL CONDITION - SELL {ot.upper()}: "
                                    f"LTP (Rs{ltp:.2f}) >= Stored adverse (Rs{adverse_price:.2f}). "
                                    f"Using current-market-based SL: Rs{sl:.2f}"
                                )
                            else:
                                # Current-based SL would be looser, stick with fixed SL
                                sl = fixed_sl
                                logger.warning(
                                    f"[WARN] EXCEPTIONAL CONDITION - SELL {ot.upper()}: "
                                    f"LTP (Rs{ltp:.2f}) >= Stored adverse (Rs{adverse_price:.2f}). "
                                    f"Current-based SL would loosen - using fixed SL: Rs{sl:.2f}"
                                )
                        
                        else:
                            # NORMAL CASE: Stored adverse price is still worse than current LTP
                            # Calculate trailing SL based on stored adverse price + buffer
                            trailing_sl = adverse_price * (1 + Config.TRAILING_BUFFER_PERCENT)
                            
                            # CRITICAL: Only use trailing SL if it tightens risk
                            # For SELL positions, tightening means a LOWER stop-loss
                            if trailing_sl < fixed_sl:
                                # Trailing SL is tighter (lower) - use it
                                sl = trailing_sl
                                
                                # Log this tightening (only once per leg)
                                state_key = f'_trailing_{ot}_logged'
                                if not self.state.get(state_key):
                                    logger.info(
                                        f" TRAILING SL ACTIVE - SELL {ot.upper()}: "
                                        f"Fixed SL: Rs{fixed_sl:.2f} -> "
                                        f"Trailing SL: Rs{sl:.2f} "
                                        f"(based on adverse Rs{adverse_price:.2f})"
                                    )
                                    self.state.set(state_key, True)
                                    
                                    # Send trailing SL notification (once when activated)
                                    if self.notifier:
                                        try:
                                            # Get both CE and PE SLs to send together
                                            if ot == 'ce':
                                                ce_strike = self.state.get('sell_ce_strike', 0)
                                                ce_sl = sl
                                                # Check if PE trailing is also active
                                                pe_strike = self.state.get('sell_pe_strike', 0)
                                                pe_entry = self.state.get('sell_pe_entry_price', 0)
                                                pe_sl = pe_entry * (1 + Config.SELL_SL_PERCENT) if pe_entry else 0
                                                
                                                # Try to get PE trailing SL if active
                                                with self._trailing_lock:
                                                    pe_adverse = self._trailing_sell_pe_adverse_price
                                                if pe_adverse:
                                                    pe_trailing_sl = pe_adverse * (1 + Config.TRAILING_BUFFER_PERCENT)
                                                    if pe_trailing_sl < pe_sl:
                                                        pe_sl = pe_trailing_sl
                                                
                                                self.notifier.send_trailing_sl_update(ce_strike, ce_sl, pe_strike, pe_sl)
                                            else:  # pe
                                                pe_strike = self.state.get('sell_pe_strike', 0)
                                                pe_sl = sl
                                                # Check if CE trailing is also active
                                                ce_strike = self.state.get('sell_ce_strike', 0)
                                                ce_entry = self.state.get('sell_ce_entry_price', 0)
                                                ce_sl = ce_entry * (1 + Config.SELL_SL_PERCENT) if ce_entry else 0
                                                
                                                # Try to get CE trailing SL if active
                                                with self._trailing_lock:
                                                    ce_adverse = self._trailing_sell_ce_adverse_price
                                                if ce_adverse:
                                                    ce_trailing_sl = ce_adverse * (1 + Config.TRAILING_BUFFER_PERCENT)
                                                    if ce_trailing_sl < ce_sl:
                                                        ce_sl = ce_trailing_sl
                                                
                                                self.notifier.send_trailing_sl_update(ce_strike, ce_sl, pe_strike, pe_sl)
                                        except Exception:
                                            pass
                            else:
                                # Trailing would loosen SL - stick with fixed
                                sl = fixed_sl
                
                except Exception:
                    # Graceful degradation: any error in trailing logic falls back to fixed SL
                    logger.exception(f"Error in trailing SL logic for SELL {ot.upper()} - using fixed SL")
                    sl = fixed_sl
            
            # else: current_time < 14:00 - use fixed_sl (already assigned)
            
            # ===== EXIT LOGIC (UNCHANGED) =====
            reason = None
            if ltp >= sl:
                reason = "SL"
            elif ltp <= tp:
                reason = "TP"
            
            if reason:
                qty = Config.LOTS * self.state.get('lot_size', 1)
                label = f"SELL_{ot.upper()}_EXIT_{reason}"
                self._place_order_safe("BUY", tok, qty, ltp, label)
                self.state.set(f'sell_{ot}_exited', True)
                pnl = (entry - ltp) * qty
                logger.info(f" SELL {ot.upper()} EXIT @ Rs{ltp:.2f} [{reason}] P&L: Rs{pnl:.2f}")
                if self.notifier:
                    try:
                        # FIX: Pass token for leg removal
                        self.notifier.send_exit(f" SELL {ot.upper()}", ltp, pnl=pnl, reason=reason, token=tok)
                    except Exception:
                        pass
        except Exception:
            logger.exception("_check_sell_exit error")

    def _check_buy_exit(self, ot):
        try:
            if not self.state.get(f'buy_{ot}_entered') or self.state.get(f'buy_{ot}_exited'):
                return
            tok = self.state.get(f'buy_{ot}_token')
            entry = self.state.get(f'buy_{ot}_entry_price')
            if not tok or entry is None:
                return
            
            # FIX: Bypass strict 5-second freshness to ensure triggers evaluate reliably
            ltp = self.feed.get_ltp(tok, check_freshness=False)
            if ltp is None:
                return
            sl = entry - Config.BUY_SL_POINTS
            tp = entry + Config.BUY_TP_POINTS
            reason = None
            if ltp <= sl:
                reason = "SL"
            elif ltp >= tp:
                reason = "TP"
            if reason:
                qty = Config.LOTS * self.state.get('lot_size', 1)
                label = f"BUY_{ot.upper()}_EXIT_{reason}"
                self._place_order_safe("SELL", tok, qty, ltp, label)
                self.state.set(f'buy_{ot}_exited', True)
                pnl = (ltp - entry) * qty
                logger.info(f" BUY {ot.upper()} EXIT @ Rs{ltp:.2f} [{reason}] P&L: Rs{pnl:.2f}")
                if self.notifier:
                    try:
                        # FIX: Pass token for leg removal
                        self.notifier.send_exit(f" BUY {ot.upper()}", ltp, pnl=pnl, reason=reason, token=tok)
                    except Exception:
                        pass
        except Exception:
            logger.exception("_check_buy_exit error")

    # -------------------------
    # TRAILING STOP-LOSS: Observation Monitor
    # -------------------------
    def _trailing_observation_monitor(self):
        """
        PURE OBSERVATION monitor for trailing stop-loss (SELL legs only).
        
        CRITICAL ENFORCEMENT:
        - 12:00-14:00: PURE observation (no SL influence, no exit triggers, no calculations)
        - 14:00: FREEZE (observation stops, no further updates allowed)
        - 14:00-14:15: NEUTRAL GAP (explicit prohibition on trailing reference)
        - 14:15: ACTIVATION (exceptional condition handling, then trailing begins)
        
        ARCHITECTURAL SEPARATION:
        - This monitor ONLY writes to tracking variables
        - This monitor NEVER reads SL, TP, or exit logic variables
        - This monitor NEVER triggers exits or modifies position state
        - Decision logic is 100% separated in _check_sell_exit
        """
        while not self._stop_event.is_set():
            try:
                current_time = ist_now().time()
                
                # ===== PHASE 1: PURE OBSERVATION WINDOW (12:00 - 14:00) =====
                if (Config.TRAILING_OBSERVATION_START <= current_time < Config.TRAILING_OBSERVATION_END):
                    # GUARD: Only track if observation window is still open
                    if not self._trailing_observation_completed:
                        # PURE OBSERVATION: Only update tracking variables
                        # NO influence on SL, NO calculations, NO exits
                        self._track_adverse_prices_pure_observation()
                
                # ===== PHASE 2: FREEZE POINT (Exactly at 14:00) =====
                elif current_time >= Config.TRAILING_OBSERVATION_END and not self._trailing_observation_completed:
                    # FREEZE: Lock observation completed flag
                    with self._trailing_lock:
                        self._trailing_observation_completed = True
                    
                    # Log frozen prices (read-only audit)
                    with self._trailing_lock:
                        ce_price = self._trailing_sell_ce_adverse_price
                        pe_price = self._trailing_sell_pe_adverse_price
                    
                    if ce_price is not None or pe_price is not None:
                        logger.info("=" * 60)
                        logger.info(" TRAILING OBSERVATION FROZEN (14:00)")
                        if ce_price is not None:
                            logger.info(f"   SELL CE adverse: Rs{ce_price:.2f} (frozen)")
                        if pe_price is not None:
                            logger.info(f"   SELL PE adverse: Rs{pe_price:.2f} (frozen)")
                        logger.info(f"    NEUTRAL GAP: 14:00-14:15 (no trailing)")
                        logger.info(f"   [OK] Trailing activates: {Config.TRAILING_ACTIVATION_TIME}")
                        logger.info("=" * 60)
                
                # ===== PHASE 3: NEUTRAL GAP (14:00 - 14:15) =====
                # EXPLICIT PROHIBITION: No tracking updates, no trailing reference
                # This elif intentionally does nothing - enforcing the dead zone
                elif Config.TRAILING_OBSERVATION_END <= current_time < Config.TRAILING_ACTIVATION_TIME:
                    # HARD BLOCK: Explicitly enforced neutral gap
                    # No code execution, no variable access, complete prohibition
                    pass  # Explicit dead-zone enforcement
                
                # ===== PHASE 4: ACTIVATION POINT (Exactly at 14:15) =====
                elif current_time >= Config.TRAILING_ACTIVATION_TIME:
                    if not self._trailing_active:
                        # ONE-TIME ACTIVATION LOGIC
                        with self._trailing_lock:
                            self._trailing_active = True
                        
                        logger.info(" TRAILING STOP-LOSS ACTIVATED (14:15)")
                        
                        # EXCEPTIONAL CONDITION: Handle case where current price
                        # is already worse than stored adverse price
                        # This is handled at activation to ensure immediate alignment
                        self._handle_exceptional_condition_at_activation()
                
            except Exception:
                logger.exception("Error in trailing observation monitor")
            
            time.sleep(1)  # Check every second
    
    def _track_adverse_prices_pure_observation(self):
        """
        PURE OBSERVATION: Track adverse prices with ZERO influence on trading logic.
        
        CRITICAL CONSTRAINTS:
        - ONLY updates tracking variables (_trailing_sell_ce/pe_adverse_price)
        - NEVER reads or modifies: SL, TP, exit flags, order state
        - NEVER triggers exits or calculations
        - NEVER calls any other methods except get_ltp
        
        This enforces architectural separation between observation and decision.
        """
        try:
            # ===== TRACK SELL CE (Independent) =====
            if self.state.get('sell_ce_entered') and not self.state.get('sell_ce_exited'):
                tok_ce = self.state.get('sell_ce_token')
                if tok_ce:
                    ltp_ce = self.feed.get_ltp(tok_ce)
                    if ltp_ce is not None:
                        with self._trailing_lock:
                            # PURE OBSERVATION: Only update tracking variable
                            # For sold options, adverse = highest price
                            if self._trailing_sell_ce_adverse_price is None:
                                self._trailing_sell_ce_adverse_price = ltp_ce
                            elif ltp_ce > self._trailing_sell_ce_adverse_price:
                                self._trailing_sell_ce_adverse_price = ltp_ce
            
            # ===== TRACK SELL PE (Completely Independent) =====
            if self.state.get('sell_pe_entered') and not self.state.get('sell_pe_exited'):
                tok_pe = self.state.get('sell_pe_token')
                if tok_pe:
                    ltp_pe = self.feed.get_ltp(tok_pe)
                    if ltp_pe is not None:
                        with self._trailing_lock:
                            # PURE OBSERVATION: Only update tracking variable
                            # For sold options, adverse = highest price
                            if self._trailing_sell_pe_adverse_price is None:
                                self._trailing_sell_pe_adverse_price = ltp_pe
                            elif ltp_pe > self._trailing_sell_pe_adverse_price:
                                self._trailing_sell_pe_adverse_price = ltp_pe
        
        except Exception:
            logger.exception("Error in pure observation tracking")
    
    def _handle_exceptional_condition_at_activation(self):
        """
        MANDATORY EXCEPTIONAL CONDITION HANDLING at 14:15 activation.
        
        SCENARIO: Current LTP >= stored adverse price from 12:00-14:00
        ACTION: Update adverse price to current LTP to align SL with market reality
        
        This is called ONCE at 14:15 activation to handle the gap between
        14:00 freeze and 14:15 activation where price may have spiked.
        
        CRITICAL: This prevents using stale adverse prices that are no longer
        representative of current market conditions.
        """
        try:
            # ===== CHECK SELL CE =====
            if self.state.get('sell_ce_entered') and not self.state.get('sell_ce_exited'):
                tok = self.state.get('sell_ce_token')
                if tok:
                    ltp = self.feed.get_ltp(tok)
                    if ltp is not None:
                        with self._trailing_lock:
                            adverse_price = self._trailing_sell_ce_adverse_price
                        
                        # EXCEPTIONAL CONDITION: Current price already worse than stored
                        if adverse_price is not None and ltp > adverse_price:
                            # MANDATORY UPDATE: Align adverse price to current market
                            with self._trailing_lock:
                                old_adverse = self._trailing_sell_ce_adverse_price
                                self._trailing_sell_ce_adverse_price = ltp
                            
                            logger.warning(
                                f"[WARN] EXCEPTIONAL CONDITION HANDLED - SELL CE:\n"
                                f"   Stored adverse (14:00): Rs{old_adverse:.2f}\n"
                                f"   Current LTP (14:15): Rs{ltp:.2f}\n"
                                f"   -> Updated adverse reference to Rs{ltp:.2f}"
                            )
            
            # ===== CHECK SELL PE (Independent) =====
            if self.state.get('sell_pe_entered') and not self.state.get('sell_pe_exited'):
                tok = self.state.get('sell_pe_token')
                if tok:
                    ltp = self.feed.get_ltp(tok)
                    if ltp is not None:
                        with self._trailing_lock:
                            adverse_price = self._trailing_sell_pe_adverse_price
                        
                        # EXCEPTIONAL CONDITION: Current price already worse than stored
                        if adverse_price is not None and ltp > adverse_price:
                            # MANDATORY UPDATE: Align adverse price to current market
                            with self._trailing_lock:
                                old_adverse = self._trailing_sell_pe_adverse_price
                                self._trailing_sell_pe_adverse_price = ltp
                            
                            logger.warning(
                                f"[WARN] EXCEPTIONAL CONDITION HANDLED - SELL PE:\n"
                                f"   Stored adverse (14:00): Rs{old_adverse:.2f}\n"
                                f"   Current LTP (14:15): Rs{ltp:.2f}\n"
                                f"   -> Updated adverse reference to Rs{ltp:.2f}"
                            )
        
        except Exception:
            logger.exception("Error handling exceptional condition at activation")
        
        except Exception:
            logger.exception("Error handling exceptional trailing condition")

    # -------------------------
    # squareoff monitor
    # -------------------------
    def _squareoff_monitor(self):
        while not self._stop_event.is_set():
            try:
                # Check hard exit first (should trigger before squareoff time)
                self._check_hard_exit()
                
                if ist_now().time() >= Config.SQUAREOFF_TIME and not self.state.get('squareoff_done'):
                    logger.warning(" SQUAREOFF")
                    # attempt to close open positions via broker API
                    try:
                        open_positions = {}
                        # try multiple broker APIs
                        if hasattr(self.broker, 'get_open_positions'):
                            open_positions = self.broker.get_open_positions()
                        elif hasattr(self.broker, 'get_positions'):
                            # convert list to dict-like {token: {'qty': qty, 'symbol': symbol}}
                            for p in self.broker.get_positions():
                                open_positions[getattr(p, 'instrument_token', getattr(p, 'token', None))] = {'qty': getattr(p, 'qty', 0), 'symbol': getattr(p, 'symbol', '')}
                        for tok, pos in list(open_positions.items()):
                            qty = abs(pos.get('qty', 0))
                            if qty == 0:
                                continue
                            side = "SELL" if pos.get('qty', 0) > 0 else "BUY"
                            ltp = self.feed.get_ltp(tok, check_freshness=False)
                            if ltp is None:
                                ltp = pos.get('last_price') or pos.get('avg_price') or 0.0
                            try:
                                self._place_order_safe(side, tok, qty, ltp, "SQUAREOFF")
                            except Exception:
                                logger.exception(f"Squareoff order failed for {tok}")
                        self.state.set('squareoff_done', True)
                    except Exception:
                        logger.exception("Error during squareoff")
                    break
            except Exception:
                pass
            
            # Enforce minimum iteration interval
            self._enforce_iteration_interval()

    # -------------------------
    # heartbeat
    # -------------------------
    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            try:
                phase = self.state.get('phase', PHASE_INIT)
                # compute pnl using broker API if available
                pnl_total = 0.0
                pnl_realized = 0.0
                pnl_unrealized = 0.0
                pos_count = 0
                try:
                    if hasattr(self.broker, 'get_pnl_breakdown'):
                        # Get detailed breakdown
                        breakdown = self.broker.get_pnl_breakdown(self.feed)
                        pnl_realized = breakdown.get('total_realized', 0.0)
                        pnl_unrealized = breakdown.get('total_unrealized', 0.0)
                        pnl_total = breakdown.get('total_net', 0.0)
                    elif hasattr(self.broker, 'get_total_pnl'):
                        pnl_total = self.broker.get_total_pnl(self.feed)
                        # Try to get breakdown
                        if hasattr(self.broker, 'get_realized_pnl'):
                            pnl_realized = self.broker.get_realized_pnl()
                        if hasattr(self.broker, 'get_unrealized_pnl'):
                            pnl_unrealized = self.broker.get_unrealized_pnl(self.feed)
                    elif hasattr(self.broker, 'get_net_pnl'):
                        # build market_prices map
                        market_prices = {}
                        for p in getattr(self.broker, 'get_positions', lambda: [])():
                            token = getattr(p, 'instrument_token', getattr(p, 'token', None))
                            if token:
                                l = self.feed.get_ltp(token, check_freshness=False)
                                market_prices[token] = l if l is not None else getattr(p, 'last_price', getattr(p, 'avg_price', 0.0))
                        pnl_total = self.broker.get_net_pnl(market_prices)
                    # position count
                    if hasattr(self.broker, 'get_open_positions'):
                        pos_count = len(self.broker.get_open_positions())
                    elif hasattr(self.broker, 'get_position_count'):
                        pos_count = self.broker.get_position_count()
                    elif hasattr(self.broker, 'get_positions'):
                        pos_count = len(self.broker.get_positions())
                except Exception:
                    logger.exception("Error computing pnl/pos for heartbeat")

                # Check feed health
                feed_status = "UNKNOWN"
                feed_msg = ""
                try:
                    if hasattr(self.feed, 'get_feed_health'):
                        health = self.feed.get_feed_health()
                        feed_status = health.get('status', 'UNKNOWN')
                        if feed_status != 'OK':
                            feed_msg = f" | FEED: {feed_status} ({health.get('message', 'N/A')})"
                            logger.warning(f"[WARN] Feed health: {health}")
                except Exception:
                    logger.exception("Error checking feed health")

                # log and notify with breakdown if available
                if pnl_realized != 0.0 or pnl_unrealized != 0.0:
                    logger.info(
                        f" {ist_now().strftime('%H:%M:%S')} | {phase} | "
                        f"R-PnL: Rs{pnl_realized:.2f} | U-PnL: Rs{pnl_unrealized:.2f} | "
                        f"Net: Rs{pnl_total:.2f} | Pos: {pos_count}{feed_msg}"
                    )
                else:
                    logger.info(f" {ist_now().strftime('%H:%M:%S')} | {phase} | P&L: Rs{pnl_total:.2f} | Pos: {pos_count}{feed_msg}")
                
                if self.notifier:
                    try:
                        # FIX: Build live leg data and pass it to heartbeat
                        legs_data = []
                        if hasattr(self.broker, 'get_open_positions'):
                            for tok, pos in self.broker.get_open_positions().items():
                                current_ltp = self.feed.get_ltp(tok, check_freshness=False)
                                if current_ltp is None:
                                    current_ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                                legs_data.append({'token': str(tok), 'ltp': current_ltp})
                        
                        self.notifier.heartbeat(phase, pnl_total, pos_count, legs=legs_data)
                    except Exception:
                        logger.exception("Notifier heartbeat failed")
            except Exception:
                logger.exception("Heartbeat loop error")
            time.sleep(max(1.0, Config.HEARTBEAT_INTERVAL))

    # -------------------------
    # helper: place order with defensive signature handling
    # -------------------------
    def _place_order_safe(self, side, token, qty, price, label=None):
        """
        Try common broker.place_order signatures:
        - place_order(side, token, qty, price, label)
        - place_order(token, symbol, side, price, qty, meta)
        - place_order(token, symbol, side, price, qty)
        - place_order(side, token, qty, price)
        """
        logger.info(f"[ORDER_SAFE] Placing order: side={side}, token={token}, qty={qty}, price={price:.2f}, label={label}, broker_mode={Config.TRADING_MODE}")

        max_retries = getattr(Config, 'ORDER_MAX_RETRIES', 3)
        retry_delay = getattr(Config, 'ORDER_RETRY_DELAY', 1.0)

        # Pre-compute symbol/meta
        symbol = None
        try:
            symbol = self.state.get(f'{token}_symbol') or self.state.get(f'{token}_symbol'.replace('_token','_symbol')) or None
        except Exception:
            symbol = None
        meta = {"label": label} if label else {}

        for attempt in range(1, max_retries + 1):
            # Block order placement if hard-exit block flag is set (requires manual reset)
            try:
                if self.state.get('hard_exit_blocked'):
                    logger.critical(f"[ORDER_SAFE] Order blocked by hard_exit_blocked flag: {side} {token} x{qty}")
                    return None
            except Exception:
                # If state access fails, log and proceed with attempts
                logger.exception("Failed to read hard_exit_blocked flag from state")

            try:
                # Try common signatures in order
                tried = False
                # sig1: (side, token, qty, price, label)
                try:
                    result = self.broker.place_order(side, token, qty, price, label)
                    tried = True
                except TypeError:
                    result = None

                if not tried or result is None:
                    # sig2: (token, symbol, side, price, qty, meta)
                    try:
                        result = self.broker.place_order(token, symbol or token, side, price, qty, meta)
                        tried = True
                    except TypeError:
                        result = None

                if not tried or result is None:
                    # sig3: (token, symbol, side, price, qty)
                    try:
                        result = self.broker.place_order(token, symbol or token, side, price, qty)
                        tried = True
                    except TypeError:
                        result = None

                if not tried or result is None:
                    # sig4: kwargs
                    try:
                        result = self.broker.place_order(side=side, token=token, qty=qty, price=price, meta=meta)
                        tried = True
                    except TypeError:
                        result = None

                # If we got a result, verify its status
                if result and isinstance(result, dict):
                    status = result.get('status', '').upper()
                    logger.info(f"[ORDER_SAFE] Attempt {attempt}/{max_retries} result status: {status}")
                    if status == 'FILLED':
                        return result
                    else:
                        # Non-filled status - log and decide whether to retry
                        logger.warning(f"[ORDER_SAFE] Non-filled order status: {status} - {result}")
                        if attempt < max_retries:
                            time.sleep(retry_delay)
                            continue
                        else:
                            return result
                elif result:
                    # Non-dict success (legacy) - return as-is
                    return result
                else:
                    # No result obtained from broker; retry if attempts remain
                    logger.warning(f"[ORDER_SAFE] No result from broker (attempt {attempt})")
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    else:
                        return None

            except Exception as e:
                logger.exception(f"[ORDER_SAFE] Exception during order attempt {attempt}: {e}")
                if self.notifier:
                    try:
                        self.notifier.send_trade_log(f"[ERROR] Order FAILED: {side} {token} @ Rs{price:.2f} x{qty} - {e}")
                    except Exception:
                        logger.exception("Notifier send_trade_log failed")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                return None

        return None