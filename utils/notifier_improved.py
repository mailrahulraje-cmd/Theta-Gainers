"""
Enhanced Telegram Notifier with State-Change Tracking
Implements clean event-based alerts with no duplicate notifications.

NOTIFICATION TYPES:
1. System Status (on change only)
2. Phase Change (on change only)
3. Lock Event (once per lock)
4. Trade Entry (once per trade)
5. Trailing SL Update (on SL change only)
6. Periodic Snapshot (at configured interval, only during IN_TRADE)
"""
import requests
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
from contract import NotifierProtocol
from constants import PHASE_INIT, PHASE_IN_TRADE

logger = logging.getLogger(__name__)
from utils.telegram_gateway import send_telegram_message


class NotificationStateCache:
    """
    In-memory cache to track last sent values and prevent duplicate alerts.
    Thread-safe state management for notification deduplication.
    """
    def __init__(self):
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
        
        # Trailing SL tracking (per leg)
        self.last_sl_ce = None
        self.last_sl_pe = None
        
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


class TradeLeg:
    """Represents a single traded option leg"""
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
        
    @property
    def pnl(self) -> float:
        """Calculate P&L for this leg (negative qty means sold/short)"""
        return -(self.current_ltp - self.entry_price) * abs(self.qty)
    
    def update_ltp(self, ltp: float):
        """Update current LTP for P&L calculation"""
        self.current_ltp = ltp
    
    def update_sl(self, sl: float):
        """Update stop loss"""
        self.current_sl = sl


class TelegramNotifierTextOnly:
    """
    State-change based Telegram notifier.
    - Event-based alerts (send only when state changes)
    - Trailing SL alerts (send only when SL modified)
    - Periodic snapshots (at configured interval, only during IN_TRADE)
    - No duplicate alerts
    - Clean, professional output
    """

    def __init__(self, bot_token: str, chat_id: str, interval: int = 30):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id is not None else None
        self.interval = max(5, int(interval))
        self.session = requests.Session()
        self._stop_event = threading.Event()
        self._thread = None
        self._validated = False
        # Last snapshot timestamp (epoch seconds)
        self._last_snapshot = 0.0

        # State tracking
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
        """Update SL for a leg"""
        with self._lock:
            if token in self.active_legs:
                self.active_legs[token].update_sl(sl)

    def get_cumulative_pnl(self) -> float:
        """Calculate cumulative P&L from all active legs"""
        with self._lock:
            return sum(leg.pnl for leg in self.active_legs.values())

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
        
        Args:
            new_phase: Phase constant from constants.py (PHASE_STANDBY, PHASE_PHASE0, etc.)
        """
        should_send, prev_phase = self.state_cache.should_send_phase_change(new_phase)
        
        if not should_send:
            return  # No change, don't send
        
        # Update current phase for snapshot control
        with self._lock:
            self.current_phase = new_phase
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        text = (
            " <b>STRATEGY PHASE CHANGE</b>\n\n"
            f"Previous: <b>{prev_phase or 'NONE'}</b>\n"
            f"Current: <b>{new_phase}</b>\n"
            f"Time: <code>{time_str}</code>"
        )
        
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
            " <b>TRADE ENTERED</b>\n\n"
            f"<b>SELL CE</b> {sell_ce_strike} @ {sell_ce_price:.2f} | SL {sell_ce_sl:.2f}\n"
            f"<b>SELL PE</b> {sell_pe_strike} @ {sell_pe_price:.2f} | SL {sell_pe_sl:.2f}\n\n"
            f"Time: <code>{time_str}</code>"
        )
        
        self._send_message(text)
        logger.info(f" Sent trade entry: CE {sell_ce_strike}, PE {sell_pe_strike}")
    
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
            " <b>TRAILING SL UPDATED</b>\n\n"
            f"Time: <code>{time_str}</code>\n\n"
            f"CE {ce_strike} SL  {ce_sl:.2f}\n"
            f"PE {pe_strike} SL  {pe_sl:.2f}"
        )
        
        self._send_message(text)
        logger.info(f" Sent trailing SL update: CE={ce_sl:.2f}, PE={pe_sl:.2f}")

    # -------------------------
    # PERIODIC SNAPSHOT (Config Controlled)
    # -------------------------
    
    def _build_snapshot_text(self) -> Optional[str]:
        """Build periodic snapshot text. Returns None if not in trade."""
        with self._lock:
            phase = self.current_phase
            legs = list(self.active_legs.values())
        
        # Only send snapshot when IN_TRADE
        if phase != PHASE_IN_TRADE or len(legs) == 0:
            return None
        
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Calculate cumulative P&L
        cum_pnl = sum(leg.pnl for leg in legs)
        pnl_emoji = "" if cum_pnl >= 0 else ""
        
        # Build text
        text = f" <b>TRADE STATUS  {time_str}</b>\n\n"
        
        # Sort legs: CE first, then PE
        sorted_legs = sorted(legs, key=lambda x: (x.option_type != "CE", x.strike))
        
        for leg in sorted_legs:
            leg_pnl_emoji = "" if leg.pnl >= 0 else ""
            
            text += (
                f"{leg_pnl_emoji} <b>{leg.option_type} {leg.strike}</b>\n"
                f"Entry: {leg.entry_price:.2f}\n"
                f"LTP: {leg.current_ltp:.2f}\n"
                f"P&L: {leg.pnl:+.2f}\n\n"
            )
        
        text += (
            "-------------------------\n"
            f"{pnl_emoji} <b>CUMULATIVE P&L: {cum_pnl:+.2f}</b>"
        )
        
        return text
    
    def _snapshot_loop(self):
        """Background loop to send periodic snapshots"""
        while not self._stop_event.is_set():
            try:
                now = time.time()
                with self._lock:
                    should_send = (now - self._last_snapshot) >= self.interval
                if should_send:
                    snapshot_text = self._build_snapshot_text()
                    if snapshot_text:
                        sent = self._send_message(snapshot_text)
                        if sent:
                            with self._lock:
                                self._last_snapshot = now
            except Exception as e:
                logger.error(f"Snapshot loop error: {e}")

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
        pnl_emoji = "" if pnl and pnl >= 0 else "" if pnl else ""
        
        text = (
            f"{pnl_emoji} <b> EXIT </b>\n\n"
            f" <b>{label}</b>\n"
            f" <b>Exit Price:</b> <code>{price:.2f}</code>\n"
        )
        
        if reason:
            text += f" <b>Reason:</b> {reason}\n"
        
        if pnl is not None:
            text += f" <b>Leg P&L:</b> <code>{pnl:+.2f}</code>\n"
        
        cum_pnl = self.get_cumulative_pnl()
        pos_count = len(self.active_legs)
        text += (
            f"\n <b>Cumulative P&L:</b> <code>{cum_pnl:+.2f}</code>\n"
            f" <b>Open Positions:</b> {pos_count}\n"
            f"\n <code>{time_str}</code>"
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
        """Send strike selection notification (backward compatibility)"""
        # This is now handled by send_lock_event()
        pass

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
        """Public helper used by logging handler and legacy callers.
        Forwards to the centralized `send_telegram_message` gateway.
        """
        return send_telegram_message(message, parse_mode=parse_mode)
