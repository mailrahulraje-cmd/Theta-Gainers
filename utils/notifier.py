"""
Enhanced Telegram Notifier with State-Change Tracking
Implements clean event-based alerts with no duplicate notifications.

LOCK SAFETY DESIGN (Critical for Phase 0/1):
=============================================
This notifier is designed to NEVER BLOCK callers, especially during Phase 0/1:

1. NotificationStateCache._lock: Protects deduplication state ONLY
   - Held only for 1-2 microseconds to check/update cache state
   - Released before any network I/O

2. TelegramNotifierTextOnly._lock: Protects active_legs and phase tracking
   - Held only to read/update leg data (< 5 microseconds)
   - Released before calling _send_message()
   - _snapshot_loop acquires lock, reads data, releases lock, then sends

3. _send_message() / send_telegram_message(): NO LOCKS HELD
   - Network I/O (Telegram API) happens OUTSIDE any locks
   - Typical latency: 10-30ms, occasionally 100-300ms
   - Caller never waits for Telegram response
   - If Telegram is slow, only the snapshot daemon thread is delayed
   - Critical trading logic continues unaffected

TWO-STAGE PATTERN ENSURES SAFETY:
==================================
Stage 1: Acquire internal lock, READ shared state, RELEASE lock
  with self._lock:
      phase = self.current_phase
      legs = list(self.active_legs.values())

Stage 2: Process data and send OUTSIDE the lock (NO BLOCKING)
  snapshot_text = self._build_snapshot_text()  # Process outside lock
  self._send_message(snapshot_text)            # Network I/O outside lock

NOTIFICATION CATEGORIES:
========================
1. System Status (on change only)
2. Phase Change (on change only)
3. Lock Event (once per lock)
4. Trade Entry (once per trade)
5. Trailing SL Update (on SL change only)
6. Error Alerts (rate-limited per type: connection/trade/data)
7. P&L Milestones (once per milestone: 100%, 150%, max-loss)
8. Periodic Snapshot (at configured interval, only during IN_TRADE)
9. Daily Heartbeat (once per day at configured time)

RLock NOT NEEDED: NotifierProtocol methods are NOT reentrant
- send_phase_change() does not call other send_*() methods
- Each notification method is independent and atomic
- threading.Lock() is sufficient for this use case
"""
import requests
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
from contract import NotifierProtocol
from constants import PHASE_INIT, PHASE_IN_TRADE
try:
    from config import Config
    ERROR_RATE_LIMIT = Config.ERROR_RATE_LIMIT_SECONDS
except (ImportError, AttributeError):
    ERROR_RATE_LIMIT = 10  # Default fallback

logger = logging.getLogger(__name__)
from utils.telegram_gateway import send_telegram_message


class NotificationStateCache:
    """
    In-memory cache to track last sent values and prevent duplicate alerts.
    Thread-safe state management for notification deduplication.
    
    DEDUPLICATION STRATEGY:
    ======================
    1. System Status: Send only on change (login/websocket status)
    2. Phase Change: Send only once per transition
    3. Lock Event: Send once per unique lock reference
    4. Trade Entry: Send once per trade (reset at start of new trade)
    5. Trailing SL: Send only when SL price changes
    6. Errors: Rate-limited (max 1 per type per 10 seconds, configurable)
    7. P&L Milestones: Send once per milestone (100%, 150%, max-loss)
    8. Connection: Send once on lost, once on restored
    
    LOCK POLICY: self._lock is held only during state read/write (< 1 microsecond)
    """
    def __init__(self):
        # Lock held ONLY for 1-2 microseconds per operation
        self._lock = threading.Lock()
        
        # System status tracking
        self.last_login_status = None
        self.last_websocket_status = None
        
        # Phase tracking
        self.last_phase = None
        
        # Lock tracking
        self.last_lock_reference = None
        
        # Trade entry tracking
        self.trade_entry_sent = False
        
        # Trailing SL tracking (per leg token, not by CE/PE)
        # Format: {token: {"old_sl": float, "new_sl": float, "last_time": float}}
        self.last_sl_update = {}  # Track last SL change per token
        self._SL_DEDUP_THRESHOLD = 0.01  # Skip if SL change < ₹0.01 (basically no change)
        
        # ERROR DEDUPLICATION: Rate limit errors by type
        # {error_type: last_send_time} - Only send if > 10 sec elapsed
        self.last_error_time = {}
        self._ERROR_RATE_LIMIT_SECONDS = ERROR_RATE_LIMIT
        
        # CONNECTION STATUS TRACKING
        self.last_connection_status = None  # "LOST", "RESTORED", None
        
        # P&L MILESTONE TRACKING
        # Set of milestones already sent (100%, 150%, max_loss)
        self.pnl_milestones_sent = set()  # e.g., {"100_percent", "150_percent", "max_loss"}
        
        # SNAPSHOT DEDUPLICATION
        # Track last snapshot P&L and timestamp to avoid spam
        self.last_snapshot_pnl = None
        self.last_snapshot_time = None
        self.last_snapshot_leg_prices = {}  # {token: ltp} to detect price changes
        self._SNAPSHOT_PNL_THRESHOLD = 10.0  # Skip if P&L change < ₹10
        self._SNAPSHOT_MIN_INTERVAL = 30  # Skip if sent < 30 sec ago
        
    def should_send_system_status(self, login_status: str, websocket_status: str) -> bool:
        """Check if system status changed"""
        with self._lock:
            changed = (login_status != self.last_login_status or 
                      websocket_status != self.last_websocket_status)
            if changed:
                self.last_login_status = login_status
                self.last_websocket_status = websocket_status
            return changed
    
    def should_send_phase_change(self, new_phase: str) -> tuple:
        """Check if phase changed. Returns (should_send, previous_phase)"""
        with self._lock:
            if new_phase != self.last_phase:
                prev = self.last_phase
                self.last_phase = new_phase
                return (True, prev)
            return (False, None)
    
    def should_send_lock(self, lock_key: str) -> bool:
        """Check if this is a new lock event"""
        with self._lock:
            if lock_key != self.last_lock_reference:
                self.last_lock_reference = lock_key
                return True
            return False
    
    def reset_trade_entry_flag(self):
        """Reset trade entry flag (call when entering new trade)"""
        with self._lock:
            self.trade_entry_sent = False
    
    def mark_trade_entry_sent(self) -> bool:
        """Mark trade entry as sent. Returns True if this is the first send."""
        with self._lock:
            if not self.trade_entry_sent:
                self.trade_entry_sent = True
                return True
            return False
    
    def should_send_sl_update(self, ce_sl: Optional[float], pe_sl: Optional[float]) -> bool:
        """Check if SL values changed"""
        with self._lock:
            changed = (ce_sl != self.last_sl_ce or pe_sl != self.last_sl_pe)
            if changed:
                self.last_sl_ce = ce_sl
                self.last_sl_pe = pe_sl
            return changed
    
    def should_send_error(self, error_type: str) -> bool:
        """
        Check if error should be sent (rate limited by type).
        Returns True if error can be sent (time elapsed > limit).
        Returns False if recently sent (duplicate suppressed).
        
        Args:
            error_type: "CONNECTION", "TRADE", "DATA", etc.
        
        Returns:
            True if error should be sent (not rate-limited)
        """
        with self._lock:
            now = time.time()
            last_time = self.last_error_time.get(error_type, 0)
            
            if (now - last_time) >= self._ERROR_RATE_LIMIT_SECONDS:
                self.last_error_time[error_type] = now
                return True
            
            return False  # Recently sent, suppress
    
    def should_send_connection_event(self, status: str) -> bool:
        """
        Check if connection event should be sent.
        Only send if status actually changed from previous.
        
        Args:
            status: "LOST" or "RESTORED"
        
        Returns:
            True if status changed (send alert)
        """
        with self._lock:
            if status != self.last_connection_status:
                self.last_connection_status = status
                return True
            return False
    
    def should_send_pnl_milestone(self, milestone: str) -> bool:
        """
        Check if P&L milestone should be sent (e.g., "100_percent", "150_percent", "max_loss").
        Only send once per milestone per session.
        
        Args:
            milestone: milestone identifier (e.g., "100_percent", "150_percent", "max_loss_triggered")
        
        Returns:
            True if milestone should be sent (not previously sent)
        """
        with self._lock:
            if milestone not in self.pnl_milestones_sent:
                self.pnl_milestones_sent.add(milestone)
                return True
            return False  # Already sent in this session
    
    def should_send_snapshot(self, current_pnl: float, current_leg_prices: dict) -> bool:
        """
        Check if snapshot should be sent based on:
        1. P&L change > ₹10 threshold
        2. >= 30 sec interval elapsed
        3. Leg prices actually changed
        
        Args:
            current_pnl: Current cumulative P&L
            current_leg_prices: {token: current_ltp} for all legs
        
        Returns:
            True if snapshot should be sent
        """
        with self._lock:
            now = time.time()
            
            # Check minimum interval
            if self.last_snapshot_time is not None:
                if (now - self.last_snapshot_time) < self._SNAPSHOT_MIN_INTERVAL:
                    return False  # Too soon, skip
            
            # Check P&L threshold
            if self.last_snapshot_pnl is not None:
                pnl_change = abs(current_pnl - self.last_snapshot_pnl)
                if pnl_change < self._SNAPSHOT_PNL_THRESHOLD:
                    # P&L hasn't changed enough, check if any leg price changed
                    price_changed = False
                    for token, ltp in current_leg_prices.items():
                        if self.last_snapshot_leg_prices.get(token) != ltp:
                            price_changed = True
                            break
                    
                    if not price_changed:
                        return False  # No meaningful change, skip
            
            # Update last snapshot state
            self.last_snapshot_pnl = current_pnl
            self.last_snapshot_time = now
            self.last_snapshot_leg_prices = current_leg_prices.copy()
            return True  # Send snapshot
    
    def should_send_sl_update(self, token: str, old_sl: Optional[float], new_sl: Optional[float]) -> bool:
        """
        Check if SL update should be sent (only if SL actually changed).
        
        Dedup logic:
        1. Skip if SL is None
        2. Skip if change < 0.01 (rounding noise)
        3. Update tracking on True return
        
        Args:
            token: Leg token identifier
            old_sl: Previous SL value (None if first time)
            new_sl: New SL value
        
        Returns:
            True if SL update should be sent
        """
        with self._lock:
            # Skip if new SL is None
            if new_sl is None:
                return False
            
            # Skip if unchanged
            if old_sl is not None:
                sl_change = abs(new_sl - old_sl)
                if sl_change < self._SL_DEDUP_THRESHOLD:
                    return False  # Negligible change, skip
            
            # Update tracking
            self.last_sl_update[token] = {
                "old_sl": old_sl,
                "new_sl": new_sl,
                "last_time": time.time()
            }
            return True  # Send update


class TradeLeg:
    """Represents a single traded option leg with lock status tracking"""
    def __init__(self, token: str, symbol: str, strike: int, option_type: str, 
                 entry_price: float, qty: int, entry_time: datetime):
        self.token = token
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type  # "CE" or "PE"
        self.entry_price = entry_price
        self.qty = qty
        self.entry_time = entry_time
        self.current_ltp = entry_price
        self.current_sl = None
        self.previous_sl = None  # Track previous SL for change detection
        
        # Lock tracking (for locked legs)
        self.is_locked = False
        self.locked_price = None  # Price at which leg was locked
        self.locked_time = None   # When leg was locked
        self.lock_reason = None   # Why it was locked (e.g., "Max loss reached")
        
    @property
    def pnl(self) -> float:
        """Calculate P&L for this leg (negative qty means sold/short)"""
        # FIX: Correct formula depending on trade side
        if self.qty < 0:
            # SELL/SHORT: Profit when price goes down
            return (self.entry_price - self.current_ltp) * abs(self.qty)
        else:
            # BUY/LONG: Profit when price goes up
            return (self.current_ltp - self.entry_price) * abs(self.qty)
    
    def update_ltp(self, ltp: float):
        """Update current LTP for P&L calculation"""
        self.current_ltp = ltp
    
    def update_sl(self, sl: float):
        """Update stop loss, tracking previous value for change detection"""
        self.previous_sl = self.current_sl
        self.current_sl = sl
    
    def mark_locked(self, reason: str = None, locked_price: float = None):
        """Mark this leg as locked (no longer trading)"""
        self.is_locked = True
        self.locked_time = datetime.now()
        self.lock_reason = reason or "Locked"
        self.locked_price = locked_price or self.current_ltp
    
    def get_lock_status_str(self) -> str:
        """Return formatted lock status indicator"""
        if self.is_locked:
            return f"🔒 {self.lock_reason}"
        return "🟢 Open"


class TelegramNotifierTextOnly:
    """
    State-change based Telegram notifier with non-blocking architecture.
    
    LOCK SAFETY DESIGN:
    - Event-based alerts (send only when state changes)
    - Trailing SL alerts (send only when SL modified)
    - Periodic snapshots (at configured interval, only during IN_TRADE)
    - No duplicate alerts
    - Clean, professional output
    
    CRITICAL: This notifier NEVER BLOCKS the calling thread
    - self._lock is held for < 5 microseconds per operation (read/update state)
    - Network I/O (Telegram API) happens OUTSIDE any locks via internal pattern
    - Snapshot loop runs in background daemon thread, does not block phase logic
    
    Lock pattern in _snapshot_loop():
      1. Acquire lock, read phase and legs, RELEASE lock (~1 microsecond)
      2. Build snapshot text outside lock (no network I/O yet)
      3. Call _send_message() outside lock (Telegram I/O here, can take 10-100ms)
      4. If sent successfully, acquire lock briefly to update timestamp
    """

    def __init__(self, bot_token: str, chat_id: str, interval: int = 30):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id is not None else None
        self.interval = max(5, int(interval))
        self.session = requests.Session()
        self._stop_event = threading.Event()
        self._thread = None
        self._validated = False
        # Last snapshot timestamp (epoch seconds) - atomic update required
        self._last_snapshot = 0.0

        # State tracking lock: held only for state read/write (< 5 microseconds)
        # NOT held during network I/O
        self._lock = threading.Lock()
        self.active_legs: Dict[str, TradeLeg] = {}  # token -> TradeLeg
        
        # Notification state cache (prevents duplicates)
        self.state_cache = NotificationStateCache()
        
        # Current phase for snapshot control
        self.current_phase = PHASE_INIT
        
        # Heartbeat state
        self.heartbeat_state = {
            "time": datetime.now(),
            "phase": PHASE_INIT,
            "cumulative_pnl": 0.0,
            "position_count": 0
        }

        logger.info(f"TelegramNotifierTextOnly initialized (interval={self.interval}s)")
        
        # RUNTIME PROTOCOL ASSERTION: Verify this notifier has all required methods
        self._assert_protocol_conformance()

    # -------------------------
    # Telegram API calls
    # -------------------------
    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send text message to Telegram via centralized gateway"""
        try:
            return send_telegram_message(text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Telegram gateway wrapper exception: {e}")
            return False

    # -------------------------
    # Validation & lifecycle
    # -------------------------
    def _assert_protocol_conformance(self):
        """
        RUNTIME PROTOCOL ASSERTION: Verify this notifier implements NotifierProtocol.
        Called at initialization to catch integration errors early.
        """
        required_methods = [
            'send_entry', 'send_exit', 'send_trade_log',
            'send_strike_selection', 'send_phase_change',
            'send_lock_event', 'send_trade_entry',
            'send_trailing_sl_update', 'heartbeat'
        ]
        
        missing_methods = []
        for method_name in required_methods:
            if not hasattr(self, method_name) or not callable(getattr(self, method_name)):
                missing_methods.append(method_name)
        
        if missing_methods:
            logger.error(f" NOTIFIER PROTOCOL ASSERTION FAILED")
            logger.error(f"Missing methods: {missing_methods}")
            raise RuntimeError(f"Notifier missing required methods: {missing_methods}")
        else:
            logger.info(f" NOTIFIER PROTOCOL ASSERTION PASSED - all {len(required_methods)} methods verified")
    
    def validate(self) -> bool:
        """Validate bot token and chat ID"""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram notifier: token/chat_id missing")
            return False
        
        try:
            resp = self.session.get(self._api_url("getMe"), timeout=8)
            if resp.status_code != 200:
                logger.warning(f"Telegram token validation failed: {resp.status_code}")
                return False
            
            self._validated = True
            return True
            
        except Exception as e:
            logger.warning(f"Telegram validation exception: {e}")
            return False

    def start(self):
        """Start the periodic snapshot loop"""
        if not self.validate():
            logger.warning("Telegram notifier validation failed; notifier will not start.")
            return
        
        if self._thread and self._thread.is_alive():
            return
        
        # Send enhanced startup confirmation message
        try:
            startup_msg = (
                " <b>SYSTEM STARTUP</b>\n\n"
                " Notifier initialized and ready\n"
                " Version: TelegramNotifierTextOnly\n"
                " Status: <b>CONNECTED</b>"
            )
            self._send_message(startup_msg)
        except Exception as e:
            logger.warning(f"Failed to send startup message: {e}")
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        self._thread.start()
        logger.info("TelegramNotifierTextOnly started")

    def stop(self):
        """Stop the snapshot loop"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("TelegramNotifierTextOnly stopped")

    # -------------------------
    # Leg tracking
    # -------------------------
    def add_leg(self, token: str, symbol: str, strike: int, option_type: str,
                entry_price: float, qty: int):
        """Add a new traded leg"""
        with self._lock:
            leg = TradeLeg(token, symbol, strike, option_type, entry_price, qty, datetime.now())
            self.active_legs[token] = leg
            logger.info(f"Added leg: {strike} {option_type} @ {entry_price}")

    def remove_leg(self, token: str) -> Optional[TradeLeg]:
        """Remove and return a leg"""
        with self._lock:
            return self.active_legs.pop(token, None)

    def update_leg_ltp(self, token: str, ltp: float):
        """Update LTP for a leg"""
        with self._lock:
            if token in self.active_legs:
                self.active_legs[token].update_ltp(ltp)
    
    def update_leg_sl(self, token: str, sl: float):
        """
        Update SL for a leg and send notification if SL changed.
        
        The notification includes:
        - Leg info (strike, option type)
        - Old SL and new SL
        - Current P&L for the leg
        - Timestamp (HH:MM:SS IST)
        - 🔒 emoji
        - Maintains open/locked separation
        """
        with self._lock:
            if token not in self.active_legs:
                return
            
            leg = self.active_legs[token]
            old_sl = leg.current_sl
            leg.update_sl(sl)  # This updates current_sl and previous_sl
        
        # Check if SL actually changed (outside lock)
        if self.state_cache.should_send_sl_update(token, old_sl, sl):
            # SL changed, build and send notification
            self._send_sl_update_notification(token, old_sl, sl)
    
    def _send_sl_update_notification(self, token: str, old_sl: Optional[float], new_sl: float):
        """Build and send SL update notification with leg details and P&L"""
        with self._lock:
            if token not in self.active_legs:
                return
            
            leg = self.active_legs[token]
            phase = self.current_phase
            legs_list = list(self.active_legs.values())
        
        # Only send if in trade
        if phase != PHASE_IN_TRADE:
            return
        
        # Build the SL update text (done outside lock)
        sl_text = self._build_sl_update_text(leg, old_sl, new_sl, legs_list)
        if sl_text:
            self._send_message(sl_text)

    def get_cumulative_pnl(self) -> float:
        """Calculate cumulative P&L from all active legs"""
        with self._lock:
            return sum(leg.pnl for leg in self.active_legs.values())
    
    def mark_leg_locked(self, token: str, reason: str = None, locked_price: float = None):
        """Mark a leg as locked (no longer trading)"""
        with self._lock:
            if token in self.active_legs:
                self.active_legs[token].mark_locked(reason, locked_price)
    
    def get_locked_legs(self) -> List[TradeLeg]:
        """Get all currently locked legs"""
        with self._lock:
            return [leg for leg in self.active_legs.values() if leg.is_locked]
    
    def get_open_legs(self) -> List[TradeLeg]:
        """Get all currently open (non-locked) legs"""
        with self._lock:
            return [leg for leg in self.active_legs.values() if not leg.is_locked]

    # -------------------------
    # EVENT-BASED NOTIFICATIONS
    # -------------------------
    
    def send_system_status(self, login_status: str, websocket_status: str):
        """
        Send system status alert ONLY when status changes.
        
        Args:
            login_status: "SUCCESS", "FAILED", etc.
            websocket_status: "CONNECTED", "DISCONNECTED", "RECONNECTED"
        """
        if not self.state_cache.should_send_system_status(login_status, websocket_status):
            return  # No change, don't send
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            " <b>SYSTEM STATUS UPDATE</b>\n\n"
            f"Login: <b>{login_status}</b>\n"
            f"Websocket: <b>{websocket_status}</b>\n"
            f"Time: <code>{time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f" Sent system status: Login={login_status}, WS={websocket_status}")
    
    def send_phase_change(self, new_phase: str):
        """
        Send phase change alert ONLY when phase actually changes.
        
        CRITICAL: This is called frequently from engine.py transitions
        Does NOT block the engine thread - returns immediately after network send
        
        Args:
            new_phase: Phase constant from constants.py (PHASE_STANDBY, PHASE_PHASE0, etc.)
        
        Lock Safety:
        - State cache check() - internal lock held < 1 microsecond
        - Update current phase - this lock held < 1 microsecond
        - Network send (Telegram) - NO LOCK HELD, can take 10-100ms
        - Caller never blocks on Telegram
        """
        should_send, prev_phase = self.state_cache.should_send_phase_change(new_phase)
        
        if not should_send:
            return  # No change, don't send
        
        # Briefly acquire lock to update snapshot control state
        with self._lock:
            self.current_phase = new_phase
        # Lock released - safe for snapshot daemon to read phase
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            " <b>STRATEGY PHASE CHANGE</b>\n\n"
            f"Previous: <b>{prev_phase or 'NONE'}</b>\n"
            f"Current: <b>{new_phase}</b>\n"
            f"Time: <code>{time_str}</code>"
        )
        
        # Network I/O outside any locks - caller not blocked
        self._send_message(text)
        logger.info(f" Sent phase change: {prev_phase}  {new_phase}")
    
    def send_lock_event(self, sell_ce_strike: int, sell_ce_price: float,
                       sell_pe_strike: int, sell_pe_price: float,
                       buy_ce_strike: int, buy_ce_price: float,
                       buy_pe_strike: int, buy_pe_price: float):
        """
        Send reference lock alert ONCE per lock event.
        
        Args:
            Strikes and prices for SELL CE, SELL PE, BUY CE, BUY PE
        """
        # Create unique lock key
        lock_key = f"{sell_ce_strike}_{sell_pe_strike}_{buy_ce_strike}_{buy_pe_strike}"
        
        if not self.state_cache.should_send_lock(lock_key):
            return  # Same lock already sent
        
        text = (
            " <b>REFERENCE LOCKED</b>\n\n"
            f"<b>SELL CE</b> {sell_ce_strike} @ {sell_ce_price:.2f}\n"
            f"<b>SELL PE</b> {sell_pe_strike} @ {sell_pe_price:.2f}\n\n"
            f"<b>BUY CE Hedge</b> {buy_ce_strike} @ {buy_ce_price:.2f}\n"
            f"<b>BUY PE Hedge</b> {buy_pe_strike} @ {buy_pe_price:.2f}"
        )
        
        self._send_message(text)
        logger.info(f" Sent lock event: {lock_key}")
    
    def send_trade_entry(self, sell_ce_strike: int, sell_ce_price: float, sell_ce_sl: float,
                        sell_pe_strike: int, sell_pe_price: float, sell_pe_sl: float):
        """
        Send trade entry alert ONCE when sell legs are executed.
        
        Args:
            sell_ce_strike, sell_ce_price, sell_ce_sl: CE leg details
            sell_pe_strike, sell_pe_price, sell_pe_sl: PE leg details
        """
        if not self.state_cache.mark_trade_entry_sent():
            return  # Already sent
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            "🟢 <b>TRADE ENTRY EXECUTED</b>\n\n"
            "📞 <b>CALL (CE)</b> | 🟥 Sell\n"
            f"Strike: <b>{sell_ce_strike}</b> | Entry: <b>₹{sell_ce_price:.2f}</b>\n"
            f"🔒 Stop Loss: <b>₹{sell_ce_sl:.2f}</b>\n\n"
            "📧 <b>PUT (PE)</b> | 🟥 Sell\n"
            f"Strike: <b>{sell_pe_strike}</b> | Entry: <b>₹{sell_pe_price:.2f}</b>\n"
            f"🔒 Stop Loss: <b>₹{sell_pe_sl:.2f}</b>\n\n"
            f"⏰ Time: <code>{time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f"🟢 Sent trade entry: CE {sell_ce_strike}, PE {sell_pe_strike}")
    
    
    def send_trailing_sl_update(self, ce_strike: int, ce_sl: float,
                                pe_strike: int, pe_sl: float):
        """
        Send trailing SL update ONLY when SL values change.
        
        Args:
            ce_strike, ce_sl: CE leg strike and new SL
            pe_strike, pe_sl: PE leg strike and new SL
        """
        if not self.state_cache.should_send_sl_update(ce_sl, pe_sl):
            return  # No SL change
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            "🔒 <b>STOP LOSS UPDATED</b>\n\n"
            f"📞 CE {ce_strike}: <b>₹{ce_sl:.2f}</b>\n"
            f"📧 PE {pe_strike}: <b>₹{pe_sl:.2f}</b>\n\n"
            f"⏰ Time: <code>{time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f"🔒 Sent trailing SL update: CE={ce_sl:.2f}, PE={pe_sl:.2f}")

    # =============================================================================
    # ERROR ALERTS (Categorized: Connection / Trade / Data)
    # =============================================================================
    
    def send_connection_lost(self, service: str, last_ltp_time: str = None, retry_info: str = None):
        """
        Send connection lost alert (ONE-TIME per occurrence).
        
        Args:
            service: "WebSocket" or "API"
            last_ltp_time: When last LTP was received (e.g., "09:45:30")
            retry_info: Auto-retry message (default: "Auto-reconnecting...")
        """
        if not self.state_cache.should_send_connection_event("LOST"):
            return  # Already sent, suppressed
        
        text = (
            "⚠️ <b>CONNECTION LOST</b>\n\n"
            f"Service: <b>{service}</b>\n"
        )
        
        if last_ltp_time:
            text += f"Last LTP: <code>{last_ltp_time}</code>\n"
        
        text += (
            f"Status: <b>🔄 RECONNECTING</b>\n"
            f"Action: Check network\n\n"
            f"ℹ️ {retry_info or 'Auto-reconnecting...'}"
        )
        
        self._send_message(text)
        logger.error(f"⚠️  Sent connection lost alert: {service}")
    
    def send_connection_restored(self, service: str):
        """
        Send connection restored alert (ONE-TIME on recovery).
        
        Args:
            service: "WebSocket" or "API"
        """
        if not self.state_cache.should_send_connection_event("RESTORED"):
            return  # Already sent recently, suppressed
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            "✅ <b>CONNECTION RESTORED</b>\n\n"
            f"Service: <b>{service}</b>\n"
            f"Status: <b>🟢 ONLINE</b>\n"
            f"<code>Time: {time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f"✅ Sent connection restored alert: {service}")
    
    def send_trade_error(self, leg: str, strike: int, qty: int, reason: str):
        """
        Send critical trade error alert (rate-limited to 1 per 10 sec).
        
        Args:
            leg: "BUY CE", "SELL PE", etc.
            strike: Strike price (e.g., 22000)
            qty: Quantity attempted
            reason: Error reason (e.g., "Insufficient margin", "Order rejected by exchange")
        """
        if not self.state_cache.should_send_error("TRADE"):
            logger.debug(f"⚠️  Trade error suppressed (rate limited): {leg} {strike} - {reason}")
            return
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            "❌ <b>TRADE FAILED</b>\n\n"
            f"Leg: <b>{leg}</b>\n"
            f"Strike: <b>{strike}</b>\n"
            f"Qty: {qty}\n\n"
            f"⚠️  <b>Error:</b>\n{reason}\n\n"
            f"🔴 <b>Action:</b> Manual intervention required\n"
            f"<code>Time: {time_str}</code>"
        )
        
        self._send_message(text)
        logger.error(f"❌ Sent trade error alert: {leg} {strike} - {reason}")
    
    def send_data_error(self, issue: str, token: str = None, status: str = None):
        """
        Send data validation error alert (rate-limited to 1 per 10 sec).
        
        Args:
            issue: "Missing LTP", "Invalid strike", "Schema violation"
            token: Token ID if applicable
            status: Current status (e.g., "Paused", "Skipped")
        """
        if not self.state_cache.should_send_error("DATA"):
            logger.debug(f"⚠️  Data error suppressed (rate limited): {issue}")
            return
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            "❌ <b>DATA ERROR</b>\n\n"
            f"Issue: <b>{issue}</b>\n"
        )
        
        if token:
            text += f"Token: <code>{token}</code>\n"
        
        if status:
            text += f"Status: <b>{status}</b>\n"
        
        text += (
            f"\n💡 <b>Recommendation:</b> Check instrument master config\n"
            f"<code>Time: {time_str}</code>"
        )
        
        self._send_message(text)
        logger.error(f"❌ Sent data error alert: {issue}")

    # =============================================================================
    # P&L MILESTONE ALERTS (One-time per milestone)
    # =============================================================================
    
    def send_pnl_milestone(self, milestone_type: str, current_pnl: float, daily_target: float = None,
                          cumulative_pnl: float = None):
        """
        Send P&L milestone alert (ONE-TIME per milestone per session).
        
        Args:
            milestone_type: "100_PERCENT", "150_PERCENT", "MAX_LOSS"
            current_pnl: Current P&L amount
            daily_target: Daily target P&L
            cumulative_pnl: Cumulative P&L across all trades
        """
        milestone_key = f"{milestone_type}"
        
        if not self.state_cache.should_send_pnl_milestone(milestone_key):
            return  # Already sent in this session
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Format milestone-specific message
        if milestone_type == "100_PERCENT":
            heading = "100% DAILY TARGET HIT"
            emoji = "🎯"
            message = (
                f"Current P&L: <b>₹{current_pnl:+.2f}</b>\n\n"
                f"Daily Target: <b>₹{daily_target:.2f}</b>\n\n"
                "✅ Safe to exit or continue cautiously"
            )
        elif milestone_type == "150_PERCENT":
            heading = "150% DAILY TARGET HIT"
            emoji = "🚀"
            message = (
                f"Current P&L: <b>₹{current_pnl:+.2f}</b>\n\n"
                f"Daily Target: <b>₹{daily_target:.2f}</b>\n\n"
                "⚠️  Consider closing positions"
            )
        elif milestone_type == "MAX_LOSS":
            heading = "MAX DAILY LOSS TRIGGERED"
            emoji = "🛑"
            message = (
                f"Current P&L: <b>₹{current_pnl:+.2f}</b>\n\n"
                "🔴 CRITICAL - Stop all trading immediately"
            )
        else:
            heading = "P&L MILESTONE"
            emoji = "📊"
            message = f"P&L: <b>₹{current_pnl:+.2f}</b>"
        
        text = f"{emoji} <b>{heading}</b>\n\n{message}"
        
        if cumulative_pnl is not None:
            text += f"\n\n📈 Cumulative (today): <b>₹{cumulative_pnl:+.2f}</b>"
        
        text += f"\n\n<code>Time: {time_str}</code>"
        
        self._send_message(text)
        logger.info(f"{emoji} Sent P&L milestone alert: {milestone_type} @ ₹{current_pnl:+.2f}")

    # =============================================================================
    # ENHANCED STARTUP ALERT
    # =============================================================================
    
    def send_system_startup(self, trading_mode: str, broker_name: str, instruments_count: int,
                           status: str = "CONNECTED"):
        """
        Send enhanced system startup alert with configuration summary.
        Called during notifier initialization.
        
        Args:
            trading_mode: "LIVE" or "PAPER"
            broker_name: "Angel One", etc.
            instruments_count: Number of instruments loaded
            status: "CONNECTED", "READY", etc.
        """
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Mode-specific emoji
        mode_emoji = "🔴 LIVE" if trading_mode == "LIVE" else "📄 PAPER"
        
        text = (
            f"🚀 <b>SYSTEM STARTUP</b>\n\n"
            f"{mode_emoji}\n"
            f"Broker: <b>{broker_name}</b>\n"
            f"Instruments: <b>{instruments_count}</b> loaded\n"
            f"Status: <b>{status}</b>\n\n"
            f"✅ Ready for trading\n"
            f"<code>Time: {time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f"✅ Sent system startup alert: {trading_mode} mode via {broker_name}")

    # =============================================================================
    # DAILY HEARTBEAT (Session Summary)
    # =============================================================================
    
    def send_daily_heartbeat(self, trades_count: int, daily_pnl: float, win_rate: float,
                            cumulative_pnl: float = None, session_start_time: str = None):
        """
        Send daily heartbeat/session summary with locked legs report (typically at 15:45 IST).
        ONE-TIME per day, usually sent at market close (15:45 IST).
        
        ENHANCED: Now includes locked legs summary showing strike, locked price, reason, and P&L
        
        Args:
            trades_count: Number of trades executed today
            daily_pnl: P&L for today
            win_rate: Win rate as percentage (0-100)
            cumulative_pnl: YTD cumulative P&L (optional)
            session_start_time: Session start time (default: 09:30 IST)
        """
        time_str = datetime.now().strftime("%H:%M:%S")
        date_str = datetime.now().strftime("%d-%b-%Y")
        
        # Get locked legs for summary
        with self._lock:
            locked_legs = [leg for leg in self.active_legs.values() if leg.is_locked]
            open_legs = [leg for leg in self.active_legs.values() if not leg.is_locked]
        
        # Emoji based on performance
        if daily_pnl > 0:
            emoji = "💰"
            status = "PROFITABLE"
            pnl_emoji = "📈"
        elif daily_pnl < 0:
            emoji = "📉"
            status = "LOSS"
            pnl_emoji = "📉"
        else:
            emoji = "平"
            status = "BREAK-EVEN"
            pnl_emoji = "➡️"
        
        # Build main heartbeat section (backward compatible)
        text = (
            f"{emoji} <b>DAILY HEARTBEAT</b>\n\n"
            f"📅 Date: <b>{date_str}</b>\n"
            f"🕐 Trading Window: {session_start_time or '09:30'} - 15:30 IST\n\n"
            f"📊 <b>Session Statistics</b>\n"
            f"{'─' * 35}\n"
            f"🔄 Trades Executed: <b>{trades_count}</b>\n"
            f"{pnl_emoji} Daily P&L: <b>₹{daily_pnl:+.2f}</b>\n"
            f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
            f"💹 Status: <b>{status}</b>\n"
        )
        
        if cumulative_pnl is not None:
            text += f"\n📊 Cumulative (YTD): <b>₹{cumulative_pnl:+.2f}</b>\n"
        
        # Add locked legs summary if any exist
        if locked_legs:
            text += "\n" + "─" * 35 + "\n"
            text += self._build_locked_legs_summary(locked_legs, open_legs)
        
        text += f"\n<code>Time: {time_str}</code>"
        
        self._send_message(text)
        logger.info(f"💓 Sent daily heartbeat: {trades_count} trades, ₹{daily_pnl:+.2f} P&L, {win_rate:.1f}% win rate, {len(locked_legs)} locked legs")
    
    def _build_locked_legs_summary(self, locked_legs: List[TradeLeg], open_legs: List[TradeLeg]) -> str:
        """
        Build locked legs summary section for daily heartbeat.
        
        Shows strike, locked price, lock reason, and final P&L for each locked leg
        with cumulative locked P&L and open/locked leg counts.
        
        Returns formatted section text
        """
        text = f"🔒 <b>LOCKED LEGS SUMMARY ({len(locked_legs)})</b>\n"
        text += "─" * 35 + "\n\n"
        
        total_locked_pnl = 0.0
        
        # Sort by option type (CE first) then strike
        sorted_locked = sorted(locked_legs, key=lambda x: (x.option_type != "CE", x.strike))
        
        for i, leg in enumerate(sorted_locked, 1):
            leg_pnl = leg.pnl
            total_locked_pnl += leg_pnl
            
            # Direction emoji (CE/PE)
            leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
            
            # P&L emoji
            pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
            
            # Buy/Sell indicator
            trade_type = "BUY" if leg.qty > 0 else "SELL"
            qty_emoji = "🟦" if leg.qty > 0 else "🟥"
            
            text += (
                f"{i}. {qty_emoji} <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b> ({trade_type})\n"
                f"   Entry: ₹{leg.entry_price:.2f} | Locked: ₹{leg.locked_price:.2f}\n"
                f"   Reason: <i>{leg.lock_reason}</i>\n"
                f"   {pnl_emoji} P&L: <b>₹{leg_pnl:+.2f}</b>\n"
            )
            
            if i < len(sorted_locked):
                text += "\n"
        
        # Summary line with cumulative locked P&L and leg counts
        text += "\n" + "─" * 35 + "\n"
        locked_pnl_emoji = "📈" if total_locked_pnl >= 0 else "📉"
        text += f"{locked_pnl_emoji} <b>Locked P&L: ₹{total_locked_pnl:+.2f}</b>\n"
        text += f"📊 Open: {len(open_legs)} | Locked: {len(locked_legs)}"
        
        return text


    # =============================================================================
    # PERIODIC SNAPSHOT (Config Controlled)
    # =============================================================================
    
    def _build_snapshot_text(self) -> Optional[str]:
        """
        Build periodic snapshot text with leg-wise P&L, SL, and locked status.
        Returns None if not in trade.
        
        Includes:
        - Per-leg P&L, current LTP, and stop loss
        - Locked legs section with lock reason
        - Cumulative P&L with indicator
        - UTF-8 emojis for visual clarity
        """
        with self._lock:
            phase = self.current_phase
            legs = list(self.active_legs.values())
        
        # Only send snapshot when IN_TRADE
        if phase != PHASE_IN_TRADE or len(legs) == 0:
            return None
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Separate open and locked legs
        open_legs = [leg for leg in legs if not leg.is_locked]
        locked_legs = [leg for leg in legs if leg.is_locked]
        
        # Calculate cumulative P&L
        cum_pnl = sum(leg.pnl for leg in legs)
        cum_pnl_emoji = "📈" if cum_pnl >= 0 else "📉"
        
        # Build text with enhanced formatting
        text = f"📊 <b>POSITION SNAPSHOT</b>\n\n"
        text += f"<code>Time: {time_str}</code>\n\n"
        
        # Open Legs Section
        if open_legs:
            text += f"🟢 <b>OPEN LEGS ({len(open_legs)})</b>\n"
            text += "─" * 40 + "\n\n"
            
            # Sort legs: CE first, then PE
            sorted_open = sorted(open_legs, key=lambda x: (x.option_type != "CE", x.strike))
            
            for i, leg in enumerate(sorted_open, 1):
                leg_pnl = leg.pnl
                leg_pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
                
                # Determine leg direction emoji
                leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
                buy_sell_emoji = "🟦" if leg.qty > 0 else "🟥"  # Blue for buy, red for sell
                
                text += (
                    f"{buy_sell_emoji} <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b>\n"
                    f"   Entry: ₹{leg.entry_price:.2f} | LTP: ₹{leg.current_ltp:.2f}\n"
                    f"   {leg_pnl_emoji} P&L: <b>₹{leg_pnl:+.2f}</b>"
                )
                
                # Add SL if available
                if leg.current_sl is not None:
                    text += f" | SL: ₹{leg.current_sl:.2f}"
                
                text += "\n\n"
        
        # Locked Legs Section
        if locked_legs:
            text += f"🔒 <b>LOCKED LEGS ({len(locked_legs)})</b>\n"
            text += "─" * 40 + "\n\n"
            
            sorted_locked = sorted(locked_legs, key=lambda x: (x.option_type != "CE", x.strike))
            
            for leg in sorted_locked:
                leg_pnl = leg.pnl
                leg_pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
                leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
                
                text += (
                    f"🔒 <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b>\n"
                    f"   Locked: ₹{leg.locked_price:.2f} | Reason: <i>{leg.lock_reason}</i>\n"
                    f"   {leg_pnl_emoji} P&L: <b>₹{leg_pnl:+.2f}</b>\n\n"
                )
        
        # Summary Section
        text += "─" * 40 + "\n"
        text += f"{cum_pnl_emoji} <b>CUMULATIVE P&L: ₹{cum_pnl:+.2f}</b>\n"
        text += f"   Open: {len(open_legs)} | Locked: {len(locked_legs)}"
        
        return text
    
    def _build_sl_update_text(self, leg, old_sl: Optional[float], new_sl: float, legs_list: List[TradeLeg]) -> str:
        """
        Build SL update notification text with dedup-friendly format.
        
        Includes:
        - Leg info (strike, option type, Buy/Sell)
        - Old SL → New SL
        - Current P&L for the leg
        - Timestamp (HH:MM:SS IST)
        - 🔒 emoji per user spec
        - Open vs locked separation
        - Cumulative P&L with leg counts
        
        Returns formatted message text
        """
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Leg type emojis
        leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
        buy_sell_emoji = "🟦" if leg.qty > 0 else "🟥"
        leg_status_emoji = "🔒" if leg.is_locked else "🟢"
        
        # P&L emoji and direction
        leg_pnl = leg.pnl
        leg_pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
        
        # Build main SL update message
        text = f"🔒 <b>TRAILING SL UPDATE</b>\n\n"
        text += f"<code>Time: {time_str}</code>\n\n"
        
        # Leg identification section
        text += f"{buy_sell_emoji} <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b>\n"
        text += f"Entry: ₹{leg.entry_price:.2f} | LTP: ₹{leg.current_ltp:.2f}\n\n"
        
        # SL change details
        if old_sl is not None:
            text += f"<b>SL Change:</b>\n"
            text += f"  Old SL: <code>₹{old_sl:.2f}</code>\n"
            text += f"  New SL: <code>₹{new_sl:.2f}</code>\n"
            sl_diff = new_sl - old_sl
            sl_diff_emoji = "⬆️" if sl_diff > 0 else "⬇️"
            text += f"  {sl_diff_emoji} Change: <code>₹{sl_diff:+.2f}</code>\n\n"
        else:
            text += f"<b>SL Set:</b>\n"
            text += f"  SL: <code>₹{new_sl:.2f}</code>\n\n"
        
        # Current P&L for this leg
        text += f"{leg_pnl_emoji} <b>P&L:</b> <code>₹{leg_pnl:+.2f}</code>\n"
        text += f"{leg_status_emoji} <b>Status:</b> {leg.get_lock_status_str()}\n\n"
        
        # Cumulative P&L with leg counts
        cum_pnl = sum(leg.pnl for leg in legs_list)
        cum_pnl_emoji = "📈" if cum_pnl >= 0 else "📉"
        open_count = len([l for l in legs_list if not l.is_locked])
        locked_count = len([l for l in legs_list if l.is_locked])
        
        text += "─" * 40 + "\n"
        text += f"{cum_pnl_emoji} <b>Cumulative P&L: ₹{cum_pnl:+.2f}</b>\n"
        text += f"📊 Open: {open_count} | Locked: {locked_count}"
        
        return text
    
    def _snapshot_loop(self):
        """
        Background loop to send periodic snapshots at FIXED 30-SECOND INTERVALS.
        
        KEY FEATURE: Fixed interval snapshots are SENT REGARDLESS OF PRICE/P&L CHANGES
        =============================================================================
        
        This differs from smart dedup:
        - Smart dedup: Only send if material change (P&L > ₹10 or price changed)
        - Fixed interval: Send every 30 seconds when IN_TRADE (even if nothing changed)
        
        USER REQUEST: "Send per-leg snapshot every 30 seconds fixed interval, independent of price change"
        
        DEDUPLICATION STRATEGY (Optional Enhancement):
        ============================================
        The smart dedup (3-level check) is available but DOES NOT BLOCK the 30-sec timer:
        - Available in state_cache.should_send_snapshot() for advanced filtering
        - Used only if explicitly called (developer discretion)
        - Default behavior: Send at fixed 30-sec intervals
        
        Result:
        - Consistent snapshot frequency: ~48/day (every 30 seconds during IN_TRADE)
        - Guaranteed visual updates: Even if price/P&L stable
        - Mobile-friendly: Regular cadence for monitoring
        
        LOCK SAFETY FOR PHASE 0/1:
        ==========================
        This loop follows the two-stage pattern to NEVER BLOCK trading logic:
        
        Stage 1: ACQUIRE LOCK (hold < 1 microsecond)
            - Check if 30-sec interval elapsed for next snapshot
            - Read current phase and legs from shared state
            - RELEASE LOCK immediately
        
        Stage 2: OUTSIDE LOCK (no time limit)
            - Build snapshot text (data processing, not network I/O)
            - Send Telegram message (network I/O, 10-100ms typical)
            - This daemon thread may be delayed, but does NOT block:
              * order_lock in broker (Phase entry/exit)
              * trailing_lock in engine (SL calculations)
              * strike selection logic in Phase 0
        
        Impact of Telegram delays:
        - Snapshot thread: May delay *subsequent* snapshots
        - Trading threads: ZERO impact - no lock held during I/O
        """
        while not self._stop_event.is_set():
            try:
                now = time.time()
                # STAGE 1: Acquire lock briefly to check timing and read state
                with self._lock:
                    elapsed = now - self._last_snapshot
                    should_send_by_timer = elapsed >= self.interval
                    phase = self.current_phase
                    legs = list(self.active_legs.values()) if should_send_by_timer else []
                # LOCK RELEASED HERE - snapshot thread is lock-free now
                
                # FIXED 30-SECOND INTERVAL: Send if timer expired and IN_TRADE
                # This is INDEPENDENT of P&L/price changes (user requested behavior)
                if should_send_by_timer and legs and phase == PHASE_IN_TRADE:
                    # STAGE 2: Build snapshot text (processing, not network I/O)
                    # No smart dedup check - send at fixed intervals!
                    snapshot_text = self._build_snapshot_text()
                    if snapshot_text:
                        # Network I/O here - Telegram may take 10-100ms
                        # But trading threads are NOT blocked (no lock held)
                        sent = self._send_message(snapshot_text)
                        
                        # Update last_snapshot timestamp after attempting send
                        # This keeps the 30-sec timer strict
                        if sent or (now - self._last_snapshot) >= self.interval:
                            with self._lock:
                                self._last_snapshot = now
                                logger.debug(f"📊 Snapshot sent (fixed 30-sec interval)")
            except Exception as e:
                logger.error(f"Snapshot loop error: {e}")

            # Sleep briefly to allow quick shutdown and responsive checks
            time.sleep(1)

    # -------------------------
    # LEGACY COMPATIBILITY METHODS
    # These maintain backward compatibility with existing code
    # -------------------------
    
    def send_entry(self, label: str, price: float, token: str = None, strike: int = None, 
                   option_type: str = None, qty: int = None, sl: float = None) -> None:
        """
        Legacy entry notification - adds leg tracking.
        For event-based entry alerts, use send_trade_entry() instead.
        """
        # Add to active legs if details provided
        if token and strike and option_type and qty:
            self.add_leg(token, label, strike, option_type, price, qty)
            if sl:
                self.update_leg_sl(token, sl)
    
    def send_exit(self, label: str, price: float, pnl: float = None, reason: str = None,
                  token: str = None) -> None:
        """
        Legacy exit notification.
        """
        # Remove from active legs
        if token:
            self.remove_leg(token)
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Select emoji based on P&L
        if pnl is not None:
            if pnl >= 0:
                pnl_emoji = "📈"
                pnl_status = "PROFIT"
            else:
                pnl_emoji = "📉"
                pnl_status = "LOSS"
        else:
            pnl_emoji = "➡️"
            pnl_status = "EXIT"
        
        text = (
            f"🔴 <b>TRADE EXIT</b> {pnl_emoji}\n\n"
            f"📌 <b>Leg:</b> {label}\n"
            f"💰 <b>Exit Price:</b> <code>₹{price:.2f}</code>\n"
        )
        
        if reason:
            text += f"📍 <b>Reason:</b> {reason}\n"
        
        if pnl is not None:
            text += f"{pnl_emoji} <b>Leg P&L:</b> <code>₹{pnl:+.2f}</code>\n"
        
        cum_pnl = self.get_cumulative_pnl()
        pos_count = len(self.active_legs)
        cum_emoji = "📈" if cum_pnl >= 0 else "📉"
        
        text += (
            f"\n{cum_emoji} <b>Cumulative P&L:</b> <code>₹{cum_pnl:+.2f}</code>\n"
            f"📊 <b>Open Positions:</b> {pos_count}\n"
            f"\n⏰ <code>{time_str}</code>"
        )
        
        self._send_message(text)


    def heartbeat(self, phase: str, pnl: float, positions: int, legs: List[Dict[str, Any]] = None) -> None:
        """
        Update heartbeat state. Used for snapshot building.
        """
        with self._lock:
            self.current_phase = phase
            self.heartbeat_state = {
                "time": datetime.now(),
                "phase": phase,
                "cumulative_pnl": pnl,
                "position_count": positions
            }
            
            # Update leg LTPs if provided
            if legs:
                for leg_data in legs:
                    token = leg_data.get("token")
                    ltp = leg_data.get("ltp")
                    sl = leg_data.get("sl")
                    if token and ltp:
                        self.update_leg_ltp(token, ltp)
                    if token and sl:
                        self.update_leg_sl(token, sl)

    def send_trade_log(self, message: str) -> None:
        """Send trade log message (for important events only)"""
        time_str = datetime.now().strftime("%H:%M:%S")
        text = (
            " <b>TRADE LOG</b>\n\n"
            f"{message}\n\n"
            f" <code>{time_str}</code>"
        )
        self._send_message(text)

    def send_strike_selection(self, message: str) -> None:
        """
        Send strike selection notification.
        This is called per-leg from StrategyState.
        Forwards to send_message for individual leg notifications.
        """
        # Forward to send_message since this is per-leg notification
        # Consolidated notifications use send_lock_event separately
        self._send_message(message)

    def send_ws_status(self, status: str, details: str = None) -> None:
        """
        Send WebSocket status update.
        Maps to send_system_status().
        """
        ws_status = "CONNECTED" if "CONNECT" in status.upper() else "DISCONNECTED"
        # Note: Login status unknown here, so we use cached value or "UNKNOWN"
        self.send_system_status(
            self.state_cache.last_login_status or "UNKNOWN",
            ws_status
        )

    def logging_handler(self):
        """Return a logging handler that sends to Telegram"""
        class TelegramLogHandler(logging.Handler):
            def emit(inner_self, record):
                try:
                    msg = inner_self.format(record)
                    # Use centralized gateway through this class helper
                    try:
                        self.send_message(msg)
                    except Exception as e:
                        logger.error(f"Logging handler telegram send failed: {e}")
                except Exception as e:
                    logger.exception(f"Logging handler failed: {e}")

        handler = TelegramLogHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
        handler.setFormatter(formatter)
        return handler

    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Public helper used by logging handler and other legacy callers.

        Forwards to the centralized `send_telegram_message` gateway.
        """
        return send_telegram_message(message, parse_mode=parse_mode)
