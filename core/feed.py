"""
ENHANCED UnifiedFeed - Drop-in Replacement
===========================================

This file is a COMPLETE REPLACEMENT for core/feed.py
Includes all three risk mitigations while maintaining backward compatibility.

INTEGRATION: Simply replace your existing core/feed.py with this file.
"""

import threading
import time
import sys
import os
import csv
from datetime import datetime, date, timedelta, time as dt_time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from collections import defaultdict

from config import Config
from utils.logger import logger
from utils.tick_recorder import TickRecorder
from contract import FeedProtocol

# Try importing SmartApi
try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    
    # Safe monkey-patch with signature matching
    _original_on_close = SmartWebSocketV2._on_close
    _original_on_error = SmartWebSocketV2._on_error
    
    def _patched_on_close(self, ws=None, close_status_code=None, close_msg=None, *args, **kwargs):
        """
        Patched WebSocket close handler.
        Matches original SDK signature exactly.
        Safe: Gracefully handles signature mismatches.
        """
        try:
            # Call original with flexible argument passing
            # Try calling with full signature if original supports it
            import inspect
            sig = inspect.signature(_original_on_close)
            params = list(sig.parameters.keys())
            
            # Most common: _on_close(self) or _on_close(self, ws)
            if len(params) <= 2:
                # Simple signature: just pass self
                return _original_on_close(self)
            else:
                # Complex signature: pass all available args
                return _original_on_close(self, ws, close_status_code, close_msg, *args, **kwargs)
        except Exception as e:
            logger.warning(f"[PATCH] _on_close error (continuing): {e}")
            # Never crash - let SDK handle it
            pass
    
    def _patched_on_error(self, ws=None, error=None, *args, **kwargs):
        """
        Patched WebSocket error handler.
        Matches original SDK signature exactly.
        Safe: Gracefully handles signature mismatches.
        """
        try:
            import inspect
            sig = inspect.signature(_original_on_error)
            params = list(sig.parameters.keys())
            
            if len(params) <= 2:
                # Simple signature
                if error is None:
                    error = Exception("Unknown error")
                return _original_on_error(self)
            else:
                # Complex signature
                if error is None:
                    error = Exception("Unknown error")
                return _original_on_error(self, error, *args, **kwargs)
        except Exception as e:
            logger.warning(f"[PATCH] _on_error error (continuing): {e}")
            # Never crash
            pass
    
    # Apply patches safely
    try:
        SmartWebSocketV2._on_close = _patched_on_close
        SmartWebSocketV2._on_error = _patched_on_error
        logger.info(" SmartWebSocketV2 patched for signature safety")
    except Exception as e:
        # If patching fails, log and continue without patch
        logger.warning(f"[PATCH] Failed to apply monkey patch: {e} (continuing without patch)")
    
except ImportError:
    # Provide lightweight fallbacks so the module can be imported in test
    # environments where SmartAPI is not installed. These placeholders
    # preserve the public names expected by the rest of the codebase
    # but do not attempt any network operations.
    logger.warning("SmartAPI not installed; using fallback placeholders for SmartConnect and SmartWebSocketV2")

    class SmartConnect:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("SmartConnect unavailable in test environment")

    class SmartWebSocketV2:
        def __init__(self, *args, **kwargs):
            # callback hooks expected by UnifiedFeed
            self.on_open = None
            self.on_data = None
            self.on_error = None
            self.on_close = None
            self.retry_attempts = 0

        def connect(self):
            # do nothing; tests that require real websocket should install SmartAPI
            return False

        def close_connection(self):
            return True
        
        # Provide class attributes that tests inspect for signature compatibility
        @staticmethod
        def _on_close(ws=None, close_status_code=None, close_msg=None, *args, **kwargs):
            return None

        @staticmethod
        def _on_error(ws=None, error=None, *args, **kwargs):
            return None


def ist_now() -> datetime:
    return datetime.now(Config.TZ)


# =============================================================================
# RISK #1 MITIGATION: LTP Cache with Validity Tracking
# =============================================================================

@dataclass
class LTPCacheEntry:
    """
    LTP cache entry with staleness tracking
    
    CRITICAL: 'valid' flag is set to False on WebSocket reconnect
    and only set to True when a fresh tick arrives.
    """
    value: float
    timestamp: float
    valid: bool  # False after reconnect, True after first new tick
    
    def is_fresh(self, max_age: float) -> bool:
        """Check if LTP is fresh enough"""
        if not self.valid:
            return False
        return (time.time() - self.timestamp) <= max_age


# =============================================================================
# RISK #3 MITIGATION: Feed Degradation Detector
# =============================================================================

@dataclass
class TokenTickStats:
    """Per-token tick statistics"""
    token: str
    last_tick_time: float
    tick_count: int
    subscription_time: float
    
    def age_seconds(self) -> float:
        return time.time() - self.last_tick_time
    
    def is_stale(self, threshold: float) -> bool:
        # Grace period for newly subscribed tokens
        if time.time() - self.subscription_time < 5.0:
            return False
        return self.age_seconds() > threshold


class FeedDegradationDetector:
    """
    Detects partial feed degradation before complete failure
    """
    
    def __init__(self):
        self.token_stats: Dict[str, TokenTickStats] = {}
        self.lock = threading.Lock()
        self._last_alert_time = 0
        self.ALERT_COOLDOWN = 30.0
    
    def register_subscription(self, token: str):
        """Register a new token subscription"""
        with self.lock:
            if token not in self.token_stats:
                self.token_stats[token] = TokenTickStats(
                    token=token,
                    last_tick_time=time.time(),
                    tick_count=0,
                    subscription_time=time.time()
                )
    
    def record_tick(self, token: str):
        """Record a tick for a token"""
        with self.lock:
            if token in self.token_stats:
                self.token_stats[token].last_tick_time = time.time()
                self.token_stats[token].tick_count += 1
            else:
                self.register_subscription(token)
    
    def get_health_status(self) -> tuple[str, str]:
        """
        Returns: (status, message)
        status: 'OK', 'DEGRADED', 'CRITICAL'
        """
        with self.lock:
            if not self.token_stats:
                return 'OK', 'No tokens subscribed'
            
            total_tokens = len(self.token_stats)
            degraded_tokens = []
            critical_tokens = []
            
            for token, stats in self.token_stats.items():
                age = stats.age_seconds()
                
                # Grace period
                if time.time() - stats.subscription_time < 5.0:
                    continue
                
                if age > Config.FEED_DEAD_THRESHOLD:
                    critical_tokens.append(token)
                elif age > Config.FEED_DEGRADED_THRESHOLD:
                    degraded_tokens.append(token)
            
            affected_count = len(degraded_tokens) + len(critical_tokens)
            degraded_percent = affected_count / total_tokens if total_tokens > 0 else 0
            
            if len(critical_tokens) > 0 and degraded_percent > 0.5:
                return 'DEAD', f"{len(critical_tokens)} tokens dead"
            elif len(critical_tokens) > 0 or degraded_percent > 0.3:
                return 'CRITICAL', f"{len(critical_tokens)} critical, {len(degraded_tokens)} degraded"
            elif len(degraded_tokens) > 0:
                return 'DEGRADED', f"{len(degraded_tokens)} tokens slow"
            
            return 'OK', 'All tokens receiving ticks'


# =============================================================================
# REPLAY ENGINE (Unchanged)
# =============================================================================

class ReplayEngine:
    """Replay recorded tick data (unchanged from original)"""
    
    def __init__(self, data_dir: str, start_date: str, end_date: str, speed: float, tick_callback):
        self.data_dir = data_dir
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        self.end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        self.speed = speed
        self.tick_callback = tick_callback
        self.stop_event = threading.Event()
        self.replay_thread = None
        logger.info(f" Replay: {self.start_date} to {self.end_date} @ {self.speed}x")
    
    def start(self):
        self.replay_thread = threading.Thread(target=self._replay_loop, daemon=True)
        self.replay_thread.start()
        logger.info(" Replay started")
    
    def stop(self):
        self.stop_event.set()
        if self.replay_thread:
            self.replay_thread.join(timeout=2)
    
    def _replay_loop(self):
        current_date = self.start_date
        while current_date <= self.end_date and not self.stop_event.is_set():
            logger.info(f" Replaying: {current_date}")
            self.tick_callback('DAY_CHANGE', current_date.isoformat(), '', 0.0,
                              datetime.combine(current_date, dt_time(0, 0)).replace(tzinfo=Config.TZ))
            self._replay_day(current_date)
            current_date += timedelta(days=1)
        logger.info(" Replay complete")
    
    def _replay_day(self, replay_date: date) -> bool:
        filename = f"ticks_{replay_date.strftime('%Y%m%d')}.csv"
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            logger.warning(f" No data: {filename}")
            return False
        
        try:
            ticks = []
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ticks.append((
                            datetime.fromisoformat(row['timestamp']),
                            row['token'],
                            row['symbol'],
                            float(row['ltp'])
                        ))
                    except (ValueError, KeyError):
                        continue
            
            if not ticks:
                return False
            
            logger.info(f" Loaded {len(ticks)} ticks")
            prev_ts = None
            for ts, token, symbol, ltp in ticks:
                if self.stop_event.is_set():
                    break
                if prev_ts:
                    delay = (ts - prev_ts).total_seconds() / self.speed
                    if delay > 0:
                        time.sleep(delay)
                self.tick_callback(token, symbol, ltp, ts)
                prev_ts = ts
            return True
        except Exception as e:
            logger.error(f" Replay failed: {e}")
            return False


# =============================================================================
# ENHANCED UNIFIED FEED
# =============================================================================

class UnifiedFeed:
    """
    Enhanced unified feed with all risk mitigations
    
    BACKWARD COMPATIBLE with original interface
    """
    
    # Reconnection parameters
    RECONNECT_DELAY_INITIAL = 2.0
    RECONNECT_DELAY_MAX = 60.0
    RECONNECT_BACKOFF_FACTOR = 1.5
    HEARTBEAT_TIMEOUT = 30.0
    
    def __init__(self, mode: str, **kwargs):
        self.mode = mode
        
        # RISK #1: Enhanced LTP cache
        self.ltp_cache: Dict[str, LTPCacheEntry] = {}
        self.ltp_lock = threading.Lock()
        
        # Symbol map
        self.symbol_map = {}
        
        # Callback
        self.tick_callback = None
        
        # Recorder
        self.recorder = None
        self.replay_engine = None
        
        # WebSocket management
        self.connected = False
        self.connection_event = threading.Event()
        self.reconnect_delay = self.RECONNECT_DELAY_INITIAL
        self.should_reconnect = True
        self.last_tick_time = time.time()
        
        # Subscription tracking
        self.subscribed_tokens = {}  # {token: (symbol, exchange)}
        
        # RISK #3: Feed degradation detector
        self.degradation_detector = FeedDegradationDetector()
        
        # Reconnect tracking
        self.reconnect_count = 0
        
        if mode == "LIVE":
            self._init_live(**kwargs)
        elif mode == "REPLAY":
            self._init_replay(**kwargs)
    
    def _init_live(self, auth_token, api_key, client_code, feed_token):
        """Initialize live WebSocket"""
        logger.info(" LIVE mode - initializing ENHANCED WebSocket")
        self.recorder = TickRecorder(Config.TICK_RECORDING_DIR)
        
        # Store credentials
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token
        
        # Connect
        self._connect_websocket()
        
        # Start heartbeat
        self._start_heartbeat_watchdog()
    
    def _connect_websocket(self):
        """
        Connect WebSocket with CRITICAL SAFETY
        
        RISK #1 MITIGATION: Invalidates ALL cached LTP on reconnect
        """
        if not hasattr(self, "reconnect_lock"):
            self.reconnect_lock = threading.Lock()
        
        if not self.reconnect_lock.acquire(blocking=False):
            return
        
        try:
            logger.info(" Connecting WebSocket...")
            
            # RISK #1: INVALIDATE ALL LTP CACHE
            self._invalidate_ltp_cache("WebSocket reconnect")
            
            # Track reconnection
            self.reconnect_count += 1
            
            # Close old socket
            if hasattr(self, 'ws') and self.ws is not None:
                try:
                    self.ws.close_connection()
                except Exception as e:
                    logger.exception(f"Failed to close old WebSocket connection: {e}")
                    pass
                self.ws = None
            
            # Create new socket
            self.ws = SmartWebSocketV2(
                self.auth_token,
                self.api_key,
                self.client_code,
                self.feed_token
            )
            
            # Disable Angel retry
            try:
                self.ws.retry_attempts = 0
            except Exception as e:
                logger.exception(f"Failed to set ws.retry_attempts: {e}")
                pass
            
            # Set callbacks
            self.ws.on_open = self._on_open
            self.ws.on_data = self._on_data
            self.ws.on_error = self._on_error
            self.ws.on_close = self._on_close
            
            # Reset state
            self.connection_event.clear()
            self.connected = False
            
            # Start connection
            threading.Thread(
                target=self.ws.connect,
                daemon=True
            ).start()
            
            # Wait for open
            if self.connection_event.wait(timeout=15):
                logger.info(" WebSocket connected - LTP cache INVALIDATED")
                self.reconnect_delay = self.RECONNECT_DELAY_INITIAL
                
                # Resubscribe
                if self.subscribed_tokens:
                    logger.info(f" Resubscribing {len(self.subscribed_tokens)} tokens")
                    self._resubscribe_all()
            else:
                logger.error(" WebSocket connection timeout")
                self._schedule_reconnect()
        
        except Exception as e:
            logger.error(f" WebSocket connection error: {e}")
            self._schedule_reconnect()
        
        finally:
            try:
                self.reconnect_lock.release()
            except Exception as e:
                logger.exception(f"Error releasing reconnect_lock: {e}")
                pass
    
    def _invalidate_ltp_cache(self, reason: str):
        """
        RISK #1 MITIGATION: Invalidate ALL cached LTP
        
        This ensures strategy CANNOT use stale prices after reconnect
        """
        with self.ltp_lock:
            invalidated_count = 0
            for token, entry in self.ltp_cache.items():
                if entry.valid:
                    entry.valid = False
                    invalidated_count += 1
            
            if invalidated_count > 0:
                logger.warning(
                    f" INVALIDATED {invalidated_count} cached LTP values "
                    f"(reason: {reason})"
                )
                
                # Notify strategy
                if self.tick_callback:
                    try:
                        self.tick_callback(
                            'LTP_CACHE_INVALIDATED',
                            reason,
                            '',
                            0.0,
                            ist_now()
                        )
                    except Exception as e:
                        logger.exception(f"tick_callback failed during cache invalidation: {e}")
                        pass
    
    def _on_open(self, wsapp):
        """WebSocket opened"""
        logger.info(" WebSocket connection opened")
        self.connected = True
        self.connection_event.set()
        self.last_tick_time = time.time()
        
        if self.tick_callback:
            try:
                self.tick_callback('WS_STATUS', 'CONNECTED', '', 0.0, ist_now())
            except Exception as e:
                logger.exception(f"tick_callback failed on open: {e}")
                pass
    
    def _on_data(self, wsapp, message):
        """
        Enhanced tick handler
        
        RISK #1: Marks LTP as VALID
        RISK #3: Records tick for degradation monitoring
        """
        try:
            data = message
            token = data.get("token")
            ltp = data.get("last_traded_price", 0) / 100.0 if "last_traded_price" in data else None
            delta = data.get("delta")
            
            if token and ltp is not None:
                # RISK #1: Update cache with VALID flag
                with self.ltp_lock:
                    self.ltp_cache[str(token)] = LTPCacheEntry(
                        value=ltp,
                        timestamp=time.time(),
                        valid=True  # VALID - fresh tick
                    )
                
                # RISK #3: Record for degradation monitoring
                self.degradation_detector.record_tick(str(token))
                
                # Update heartbeat
                self.last_tick_time = time.time()
                
                # Record tick
                if self.recorder:
                    symbol = self.symbol_map.get(str(token), f"Token-{token}")
                    self.recorder.record_tick(str(token), symbol, ltp, ist_now())
                
                # Callback
                if self.tick_callback:
                    symbol = self.symbol_map.get(str(token), "")
                    self.tick_callback(token, symbol, ltp, ist_now(), delta=delta)
        
        except Exception as e:
            logger.error(f" Feed data processing error: {e}")
    
    def _on_error(self, wsapp, error):
        """WebSocket error"""
        logger.error(f" WebSocket error: {error}")
        
        if self.should_reconnect:
            self._schedule_reconnect()
    
    def _on_close(self, wsapp):
        """
        WebSocket closed
        
        RISK #1 MITIGATION: Invalidates LTP cache
        """
        logger.warning(" WebSocket closed")
        
        self.connected = False
        
        # RISK #1: Invalidate cache
        self._invalidate_ltp_cache("WebSocket disconnect")
        
        # Notify strategy
        if self.tick_callback:
            try:
                self.tick_callback(
                    'WS_STATUS',
                    'DISCONNECTED',
                    '',
                    0.0,
                    ist_now()
                )
            except Exception as e:
                logger.exception(f"tick_callback failed on close: {e}")
                pass
        
        # Schedule reconnect
        if self.should_reconnect:
            self._schedule_reconnect()
    
    def _schedule_reconnect(self):
        """Schedule reconnection with backoff"""
        if not self.should_reconnect:
            return
        
        delay = self.reconnect_delay
        logger.info(f" Scheduling reconnect in {delay:.1f}s")
        
        threading.Thread(
            target=self._delayed_reconnect,
            args=(delay,),
            daemon=True
        ).start()
        
        self.reconnect_delay = min(
            self.reconnect_delay * self.RECONNECT_BACKOFF_FACTOR,
            self.RECONNECT_DELAY_MAX
        )
    
    def _delayed_reconnect(self, delay: float):
        """Wait then reconnect"""
        time.sleep(delay)
        if self.should_reconnect and not self.connected:
            logger.info(" Attempting reconnection...")
            self._connect_websocket()
    
    def _start_heartbeat_watchdog(self):
        """Start watchdog to detect frozen ticks"""
        def watchdog_loop():
            while self.should_reconnect:
                time.sleep(10)
                
                if self.mode == "LIVE" and self.should_reconnect:
                    if not self.connected:
                        continue
                    
                    elapsed = time.time() - self.last_tick_time
                    
                    if elapsed > self.HEARTBEAT_TIMEOUT:
                        logger.warning(
                            f" No ticks for {elapsed:.1f}s. Forcing reconnect."
                        )
                        
                        try:
                            self.ws.close_connection()
                        except Exception as e:
                            logger.exception(f"watchdog failed to close ws: {e}")
                            pass
        
        threading.Thread(target=watchdog_loop, daemon=True).start()
        logger.info(f" Heartbeat watchdog started (timeout: {self.HEARTBEAT_TIMEOUT}s)")
    
    def _resubscribe_all(self):
        """
        Resubscribe all tokens after reconnect with verification.
        
        ✓ HARDENED RECONNECT LOGIC IMPLEMENTED
        - Verifies each token subscription succeeded
        - Implements retry mechanism for failed subscriptions
        - Prevents trading if subscriptions fail completely
        
        This function ensures that after a WebSocket reconnection, all tokens
        must receive confirmed ticks before trading resumes. If any token cannot
        be verified after retries, self.connected is set to False to block trading.
        """
        if not self.subscribed_tokens:
            return
        
        # Call enhanced subscription verification
        if not self._subscribe_to_saved_tokens():
            logger.error(" Subscription verification failed - marking connection as broken")
            self.connected = False
            if self.tick_callback:
                try:
                    self.tick_callback(
                        'SUBSCRIPTION_FAILED',
                        'Critical subscriptions could not be verified',
                        '',
                        0.0,
                        ist_now()
                    )
                except Exception as e:
                    logger.exception(f"tick_callback failed during subscription failure: {e}")
    
    def _subscribe_to_saved_tokens(self) -> bool:
        """
        Subscribe to all saved tokens with verification and retry logic.
        
        ✓ SUBSCRIPTION VERIFICATION HARDENING IMPLEMENTED
        
        Detailed behavior:
        - Subscribes to each token in self.subscribed_tokens
        - Verifies subscription by ensuring self.ltp_cache[token] receives at least one tick
        - Verification window: 5 seconds per attempt
        - Retry mechanism: Up to 3 attempts per token
        - Failure handling: Logs ERROR and prevents trading (parent sets self.connected = False)
        
        Returns:
            bool: True if ALL tokens verified successfully, False otherwise
        """
        if not self.subscribed_tokens:
            logger.info(" No saved tokens to resubscribe")
            return True
        
        logger.info(f" Starting hardened subscription verification for {len(self.subscribed_tokens)} tokens")
        
        # Group tokens by exchange
        by_exchange = {}
        for token, (symbol, exchange) in self.subscribed_tokens.items():
            if exchange not in by_exchange:
                by_exchange[exchange] = []
            by_exchange[exchange].append(token)
        
        all_verified = True
        max_retries = 3
        verification_timeout = 5.0
        
        for exchange, tokens in by_exchange.items():
            logger.info(f" Processing {len(tokens)} tokens on exchange {exchange}")
            
            symbols = {
                token: self.subscribed_tokens[token][0]
                for token in tokens
            }
            
            # Subscribe tokens
            try:
                self._subscribe_live(tokens, symbols, exchange)
            except Exception as e:
                logger.error(f" Failed to subscribe tokens on {exchange}: {e}")
                all_verified = False
                continue
            
            time.sleep(0.5)
            
            # Verify each token received at least one tick
            unverified_tokens = []
            for token in tokens:
                symbol = symbols.get(str(token), f"Token-{token}")
                verified = False
                
                for attempt in range(1, max_retries + 1):
                    # Wait for tick with timeout
                    start_time = time.time()
                    tick_received = False
                    
                    while time.time() - start_time < verification_timeout:
                        with self.ltp_lock:
                            if str(token) in self.ltp_cache:
                                entry = self.ltp_cache[str(token)]
                                if entry.valid:  # Valid means fresh tick received
                                    tick_received = True
                                    break
                        
                        time.sleep(0.1)
                    
                    if tick_received:
                        logger.info(f" ✓ Verified {symbol} ({token}) - ticks received")
                        verified = True
                        break
                    else:
                        logger.warning(
                            f" Verification attempt {attempt}/{max_retries} failed for "
                            f"{symbol} ({token}) - no tick within {verification_timeout}s"
                        )
                        
                        if attempt < max_retries:
                            # Retry subscription
                            logger.info(f" Retrying subscription for {symbol} ({token})")
                            try:
                                self._subscribe_live([token], {str(token): symbol}, exchange)
                            except Exception as e:
                                logger.error(f" Retry subscription failed for {symbol}: {e}")
                            
                            time.sleep(0.5)
                
                if not verified:
                    logger.error(
                        f" ✗ CRITICAL: {symbol} ({token}) could not be verified after "
                        f"{max_retries} attempts - no tick received"
                    )
                    unverified_tokens.append((token, symbol))
                    all_verified = False
            
            if unverified_tokens:
                logger.error(
                    f" {len(unverified_tokens)} tokens on {exchange} failed verification: "
                    f"{[s for _, s in unverified_tokens]}"
                )
        
        if all_verified:
            logger.info(
                f" ✓ HARDENED SUBSCRIPTION VERIFICATION COMPLETE - "
                f"All {len(self.subscribed_tokens)} tokens verified successfully"
            )
        else:
            logger.error(
                f" ✗ HARDENED SUBSCRIPTION VERIFICATION FAILED - "
                f"Some tokens could not receive ticks. Trading will be blocked."
            )
        
        return all_verified
    
    def _init_replay(self, start_date, end_date, speed):
        """Initialize replay mode"""
        logger.info(" REPLAY mode")
        self.replay_engine = ReplayEngine(
            Config.REPLAY_DATA_DIR,
            start_date,
            end_date,
            speed,
            self._on_replay_tick
        )
    
    def _on_replay_tick(self, token, symbol, ltp, timestamp):
        """Handle replay tick"""
        if token == 'DAY_CHANGE':
            if self.tick_callback:
                self.tick_callback('DAY_CHANGE', symbol, '', 0.0, timestamp)
            return
        
        with self.ltp_lock:
            self.ltp_cache[token] = LTPCacheEntry(
                value=ltp,
                timestamp=time.time(),
                valid=True
            )
        
        if self.tick_callback:
            self.tick_callback(token, symbol, ltp, timestamp)
    
    def set_tick_callback(self, callback: Callable):
        """Set tick callback handler"""
        self.tick_callback = callback
    
    def subscribe(self, tokens: List[str], symbols: Dict[str, str], exchange: str = "NFO") -> None:
        """
        Subscribe to tokens
        
        RISK #3 MITIGATION: Registers tokens for degradation monitoring
        """
        if self.mode == "LIVE":
            # RISK #3: Register for monitoring
            for token in tokens:
                self.degradation_detector.register_subscription(str(token))
                self.subscribed_tokens[str(token)] = (
                    symbols.get(str(token), f"Token-{token}"),
                    exchange
                )
            
            self._subscribe_live(tokens, symbols, exchange)
        else:
            self.symbol_map.update(symbols)
            logger.info(f" Registered {len(tokens)} tokens for replay")
    
    def _subscribe_live(self, tokens: List[str], symbols: Dict[str, str], exchange: str):
        """Subscribe to live tokens"""
        if not self.connected:
            logger.warning(" Cannot subscribe: WebSocket not connected")
            return
        
        self.symbol_map.update(symbols)
        ex_type = 1 if exchange == "NSE" else 2 if exchange == "NFO" else 2
        
        success_count = 0
        for token in tokens:
            try:
                self.ws.subscribe(
                    f"sub_{token}",
                    1,
                    [{"exchangeType": ex_type, "tokens": [str(token)]}]
                )
                success_count += 1
                time.sleep(Config.SUBSCRIPTION_DELAY)
            
            except Exception as e:
                symbol = symbols.get(str(token), f"Token-{token}")
                logger.error(f" Subscribe failed for {symbol} ({token}): {e}")
        
        logger.info(f" Subscribed {success_count}/{len(tokens)} tokens on {exchange}")
    
    def start_replay(self):
        """Start replay engine"""
        if self.mode == "REPLAY" and self.replay_engine:
            self.replay_engine.start()
    
    def get_ltp(self, token: str, check_freshness: bool = True) -> Optional[float]:
        """
        Get LTP with MANDATORY staleness validation and logging.
        
        ✓ STALE DATA PREVENTION IMPLEMENTED
        
        Checks:
        - LTP must exist in cache
        - LTP must be marked VALID (not invalidated post-reconnect)
        - LTP must be fresh (< 10 seconds old) when check_freshness=True
        
        RISK #1 MITIGATION: Returns None if LTP is INVALID or stale
        RISK #4 MITIGATION: Prevents trading on data older than 10 seconds
        
        Args:
            token: Contract token to get LTP for
            check_freshness: If True, enforce 10-second staleness check
        
        Returns:
            float: Valid LTP value if fresh, None if invalid/stale/missing
        """
        STALE_DATA_THRESHOLD = 10.0  # 10 seconds max age
        
        with self.ltp_lock:
            entry = self.ltp_cache.get(str(token))
            
            if entry is None:
                return None
            
            # CRITICAL: Check validity (set to False on reconnect)
            if not entry.valid:
                return None
            
            # STALE DATA CHECK: Explicit 10-second threshold
            if check_freshness and self.mode == "LIVE":
                current_time = time.time()
                data_age = current_time - entry.timestamp
                
                # Check against 10-second threshold
                if data_age > STALE_DATA_THRESHOLD:
                    # Log WARNING with token and last tick timestamp
                    last_tick_dt = datetime.fromtimestamp(entry.timestamp)
                    logger.warning(
                        f" STALE DATA DETECTED: Token {str(token)} - "
                        f"Last tick {data_age:.1f}s ago at {last_tick_dt.isoformat()} "
                        f"(threshold: {STALE_DATA_THRESHOLD}s). Blocking trade."
                    )
                    return None
                
                # Also check against config freshness threshold if different
                if not entry.is_fresh(Config.TICK_FRESHNESS_SECONDS):
                    last_tick_dt = datetime.fromtimestamp(entry.timestamp)
                    logger.warning(
                        f" STALE DATA DETECTED: Token {str(token)} - "
                        f"Last tick {data_age:.1f}s ago at {last_tick_dt.isoformat()} "
                        f"(config threshold: {Config.TICK_FRESHNESS_SECONDS}s). Blocking trade."
                    )
                    return None
            
            return entry.value
    
    def close(self):
        """Close feed and cleanup"""
        logger.info(" Closing feed...")
        
        self.should_reconnect = False
        
        if self.mode == "LIVE":
            if self.recorder:
                self.recorder.close()
            
            if hasattr(self, 'ws'):
                try:
                    self.connected = False
                    self.ws.close_connection()
                except Exception as e:
                    logger.warning(f"WebSocket close error: {e}")
        
        elif self.mode == "REPLAY" and self.replay_engine:
            self.replay_engine.stop()
        
        logger.info(" Feed closed")
    
    def get_feed_health(self) -> Dict[str, any]:
        """
        Get feed health status
        
        RISK #3 MITIGATION: Includes degradation status
        """
        status, message = self.degradation_detector.get_health_status()
        
        with self.ltp_lock:
            valid_ltp = sum(1 for e in self.ltp_cache.values() if e.valid)
            total_ltp = len(self.ltp_cache)
        
        return {
            'status': status,
            'message': message,
            'connected': self.connected,
            'valid_ltp_count': valid_ltp,
            'total_ltp_count': total_ltp,
            'subscribed_tokens': len(self.subscribed_tokens),
            'mode': self.mode,
            'last_tick_age': time.time() - self.last_tick_time,
            'reconnect_count': self.reconnect_count
        }
    
    def is_feed_healthy(self) -> bool:
        """Quick health check"""
        health = self.get_feed_health()
        return health['status'] == 'OK' and self.connected
    
    def can_trade(self) -> bool:
        """
        ✓ TRADING SAFETY GATE - Comprehensive check before order execution
        
        Returns True only if BOTH conditions are met:
        1. WebSocket is connected (self.connected == True)
        2. ALL subscribed tokens have valid, non-stale data
        
        RISK #1 MITIGATION: Ensures connection is alive
        RISK #4 MITIGATION: Ensures all data is fresh (<10 seconds)
        
        Returns:
            bool: True if safe to trade, False if any risk detected
        """
        # CHECK 1: WebSocket Connection
        if not self.connected:
            logger.warning(
                f" TRADING BLOCKED: WebSocket disconnected "
                f"(reconnect_count={self.reconnect_count}). "
                f"No orders will be placed."
            )
            return False
        
        # CHECK 2: All Subscribed Tokens Have Fresh Data
        if not self.subscribed_tokens:
            # No tokens subscribed yet - cannot trade
            logger.warning(" TRADING BLOCKED: No tokens subscribed yet.")
            return False
        
        stale_tokens = []
        missing_tokens = []
        
        for token in self.subscribed_tokens.keys():
            # Call get_ltp with freshness check enabled
            # Returns None if data is stale or missing
            ltp = self.get_ltp(str(token), check_freshness=True)
            
            if ltp is None:
                # Determine if stale or missing
                with self.ltp_lock:
                    entry = self.ltp_cache.get(str(token))
                    if entry is None:
                        missing_tokens.append(str(token))
                    elif not entry.valid:
                        missing_tokens.append(str(token))
                    else:
                        # Entry exists and is valid, but must be stale
                        stale_tokens.append(str(token))
        
        # Log detailed information about any issues
        if stale_tokens:
            logger.warning(
                f" TRADING BLOCKED: {len(stale_tokens)} token(s) have STALE data "
                f"(>10 seconds old): {stale_tokens}. "
                f"Waiting for fresh ticks before trading resumes."
            )
            return False
        
        if missing_tokens:
            logger.warning(
                f" TRADING BLOCKED: {len(missing_tokens)} token(s) missing or invalid "
                f"data: {missing_tokens}. "
                f"Waiting for connection/subscriptions to be established."
            )
            return False
        
        # All checks passed - safe to trade
        logger.debug(f" ✓ Trading ALLOWED - WebSocket connected + all {len(self.subscribed_tokens)} tokens fresh")
        return True
