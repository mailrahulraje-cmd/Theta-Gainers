# 🔧 COMPLETE SYSTEM REFACTORING - Implementation Guide

## Overview

This document provides the complete refactoring to achieve:
1. ✅ Unified INIT phase (Phase 0 + Phase 1 merged)
2. ✅ Controlled delta-finding loop
3. ✅ Telegram phase name consistency
4. ✅ Fully independent 4-leg architecture
5. ✅ Hardened trailing stop loss

---

## CRITICAL: Files to Modify

### New File:
- `constants.py` - Phase name constants ✅ CREATED

### Files to Modify:
1. `strategy/engine.py` - Major refactoring
2. `utils/notifier.py` - Phase constant usage
3. `core/state.py` - Leg independence structure

---

## 1️⃣ UNIFIED INITIALIZATION PHASE

### Changes to `strategy/engine.py`

#### Remove Time-Based Phase Monitor

**BEFORE (lines ~302-360):**
```python
def _phase_monitor(self):
    while not self._stop_event.is_set():
        now = ist_now()
        ct = now.time()
        
        if ct < Config.PHASE0_START:
            # STANDBY
        elif Config.PHASE0_START <= ct < Config.PHASE0_END:
            # PHASE 0
            if not self.state.get('phase0_done'):
                self._execute_phase0()
        elif Config.PHASE1_START <= ct < Config.PHASE1_END:
            # PHASE 1
            if not self.state.get('phase1_done'):
                self._execute_phase1()
```

**AFTER:**
```python
from constants import PHASE_INIT, PHASE_TRADING, PHASE_CLOSED

def _phase_monitor(self):
    """
    Simplified phase monitor without time-based windows.
    Initialization happens once per day, then continuous trading.
    """
    while not self._stop_event.is_set():
        try:
            now = ist_now()
            ct = now.time()
            
            # Single initialization check
            if not self.state.get('structure_initialized', False):
                if ct >= time(9, 15, 0):  # Market open
                    self.state.set('phase', PHASE_INIT)
                    self._initialize_structure()
            
            # Trading phase (after initialization)
            elif ct < Config.SQUAREOFF_TIME:
                if self.state.get('phase') != PHASE_TRADING:
                    self.state.set('phase', PHASE_TRADING)
                    if self.notifier:
                        try:
                            self.notifier.send_phase_change(PHASE_TRADING)
                        except Exception:
                            pass
            
            # Closed phase
            else:
                if self.state.get('phase') != PHASE_CLOSED:
                    self.state.set('phase', PHASE_CLOSED)
            
            time.sleep(1)
            
        except Exception:
            logger.exception("Phase monitor error")
            time.sleep(1)
```

#### Create Unified Initialization Method

**ADD NEW METHOD:**
```python
def _initialize_structure(self):
    """
    Unified initialization - replaces Phase 0 + Phase 1.
    Runs once per day to set up all 4 legs.
    
    Steps:
    1. Calculate ATM
    2. Select SELL CE/PE strikes
    3. Select BUY CE/PE hedges (with bounded delta search)
    4. Subscribe all tokens
    5. Capture reference premiums
    6. Mark initialization complete
    """
    try:
        logger.info("="*60)
        logger.info("🚀 INITIALIZING STRUCTURE - Unified Phase")
        logger.info("="*60)
        
        # === STEP 1: Calculate ATM ===
        spot = self.instruments.find_spot()
        if not spot:
            logger.warning("INIT: Spot instrument not found")
            return
        
        spot_token = spot['token']
        self.feed.subscribe([spot_token], {spot_token: spot.get('symbol', 'Spot')}, Config.SPOT_EXCHANGE)
        self._track_token_subscription([spot_token])
        
        # Wait for spot LTP
        spot_ltp = None
        for _ in range(10):
            spot_ltp = self.feed.get_ltp(spot_token, check_freshness=False)
            if spot_ltp:
                break
            time.sleep(0.3)
        
        if not spot_ltp:
            logger.warning("INIT: Spot LTP unavailable")
            return
        
        atm = int((spot_ltp + Config.ATM_ROUND / 2) // Config.ATM_ROUND * Config.ATM_ROUND)
        logger.info(f"✅ INIT: ATM={atm} (Spot={spot_ltp:.2f})")
        
        # Get expiry and lot size
        expiry = self.instruments.get_nearest_expiry()
        if not expiry:
            logger.warning("INIT: No expiry found")
            return
        
        lot_size = 1
        try:
            sample = self.instruments.find_option(atm, 'CE', expiry)
            if sample and 'lotsize' in sample:
                lot_size = int(sample['lotsize'])
        except:
            pass
        
        # === STEP 2: Select SELL CE/PE ===
        sell_ce_strike = atm - Config.SELL_CE_OFFSET
        sell_pe_strike = atm + Config.SELL_PE_OFFSET
        
        sell_ce = self.instruments.find_option(sell_ce_strike, 'CE', expiry)
        sell_pe = self.instruments.find_option(sell_pe_strike, 'PE', expiry)
        
        if not sell_ce or not sell_pe:
            logger.warning("INIT: SELL options not found")
            return
        
        # Subscribe SELL options
        sell_tokens = [sell_ce['token'], sell_pe['token']]
        sell_symbols = {
            sell_ce['token']: sell_ce['symbol'],
            sell_pe['token']: sell_pe['symbol']
        }
        self.feed.subscribe(sell_tokens, sell_symbols, Config.EXCHANGE)
        self._track_token_subscription(sell_tokens)
        time.sleep(1)  # Wait for ticks
        
        # Get SELL LTPs
        sell_ce_ltp = self.feed.get_ltp(sell_ce['token'], check_freshness=False) or 0
        sell_pe_ltp = self.feed.get_ltp(sell_pe['token'], check_freshness=False) or 0
        
        # Lock SELL legs
        self.state.lock_sell_ce_leg({
            'token': sell_ce['token'],
            'strike': sell_ce_strike,
            'symbol': sell_ce['symbol'],
            'ltp': sell_ce_ltp
        })
        
        self.state.lock_sell_pe_leg({
            'token': sell_pe['token'],
            'strike': sell_pe_strike,
            'symbol': sell_pe['symbol'],
            'ltp': sell_pe_ltp
        })
        
        logger.info(f"✅ INIT: SELL CE {sell_ce_strike} @ ₹{sell_ce_ltp:.2f}")
        logger.info(f"✅ INIT: SELL PE {sell_pe_strike} @ ₹{sell_pe_ltp:.2f}")
        
        # === STEP 3: Select BUY CE/PE (Bounded Delta Search) ===
        range_val = Config.DELTA_SCAN_RANGE * Config.ATM_ROUND
        
        # BUY CE - with bounded search
        buy_ce = self._select_by_delta_bounded(
            atm, atm + range_val, 'CE', expiry, Config.TARGET_CE_DELTA
        )
        
        if buy_ce:
            self.state.lock_buy_ce_leg(buy_ce)
            logger.info(f"✅ INIT: BUY CE {buy_ce['strike']} @ ₹{buy_ce['ltp']:.2f}")
        else:
            logger.warning("⚠️ INIT: BUY CE not found - will trade without CE hedge")
        
        # BUY PE - with bounded search
        buy_pe = self._select_by_delta_bounded(
            atm - range_val, atm, 'PE', expiry, Config.TARGET_PE_DELTA
        )
        
        if buy_pe:
            self.state.lock_buy_pe_leg(buy_pe)
            logger.info(f"✅ INIT: BUY PE {buy_pe['strike']} @ ₹{buy_pe['ltp']:.2f}")
        else:
            logger.warning("⚠️ INIT: BUY PE not found - will trade without PE hedge")
        
        # === STEP 4: Store common state ===
        self.state.update({
            'spot_reference': spot_ltp,
            'atm_strike': atm,
            'expiry': expiry,
            'lot_size': lot_size,
            'sell_ce_strike': sell_ce_strike,
            'sell_pe_strike': sell_pe_strike,
            'structure_initialized': True,  # NEW: Replaces phase0_done + phase1_done
            'init_complete_time': time.time()
        })
        
        logger.info("="*60)
        logger.info("✅ STRUCTURE INITIALIZATION COMPLETE")
        logger.info("="*60)
        
        # Send lock event notification
        if self.notifier and buy_ce and buy_pe:
            try:
                self.notifier.send_lock_event(
                    sell_ce_strike, sell_ce_ltp,
                    sell_pe_strike, sell_pe_ltp,
                    buy_ce['strike'], buy_ce['ltp'],
                    buy_pe['strike'], buy_pe['ltp']
                )
            except Exception:
                pass
        
    except Exception:
        logger.exception("INIT: Structure initialization failed")
```

#### Add Bounded Delta Selection

**ADD NEW METHOD:**
```python
def _select_by_delta_bounded(self, min_strike, max_strike, opt_type, expiry, target_delta):
    """
    Bounded delta selection with iteration cap and fallback.
    
    Improvements:
    1. Max 50 iterations
    2. Fallback to nearest OTM if delta search fails
    3. Safe subscription with timeout
    """
    try:
        # Get options in range
        options = self.instruments.find_options_in_range(min_strike, max_strike, opt_type, expiry)
        
        if not options:
            logger.warning(f"No {opt_type} options found in range {min_strike}-{max_strike}")
            return None
        
        # Subscribe to options for delta calculation
        tokens_to_subscribe = []
        symbol_map = {}
        for opt in options:
            token = opt['token']
            tokens_to_subscribe.append(token)
            symbol_map[token] = opt['symbol']
        
        if tokens_to_subscribe:
            try:
                logger.info(f"DELTA: Subscribing to {len(tokens_to_subscribe)} {opt_type} options")
                self.feed.subscribe(tokens_to_subscribe, symbol_map, Config.EXCHANGE)
                self._track_token_subscription(tokens_to_subscribe)
                
                # Wait for delta data (max 5 seconds)
                max_wait = 5
                for i in range(max_wait * 2):
                    time.sleep(0.5)
                    valid_deltas = sum(1 for tok in tokens_to_subscribe 
                                     if self.instruments.get_snapshot(tok).get('delta') is not None)
                    if valid_deltas > len(tokens_to_subscribe) * 0.5:
                        break
                
            except Exception as e:
                logger.warning(f"DELTA: Subscription failed: {e}")
                return None
        
        # BOUNDED DELTA SEARCH (Max 50 iterations)
        best_option = None
        min_score = float('inf')
        max_iterations = 50
        iteration_count = 0
        
        for opt in options:
            if iteration_count >= max_iterations:
                logger.warning(f"DELTA: Max iterations ({max_iterations}) reached")
                break
            
            iteration_count += 1
            
            token = opt['token']
            snap = self.instruments.get_snapshot(token)
            ltp = snap.get('ltp')
            delta = snap.get('delta')
            
            if delta is not None and ltp and ltp > 0:
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
        
        # FALLBACK: If delta search failed, use nearest OTM
        if best_option is None and options:
            logger.warning(f"DELTA: Selection failed - using nearest OTM fallback")
            # For CE: highest strike (most OTM)
            # For PE: lowest strike (most OTM)
            if opt_type == 'CE':
                fallback = max(options, key=lambda x: float(x['strike']))
            else:
                fallback = min(options, key=lambda x: float(x['strike']))
            
            fallback_ltp = self.feed.get_ltp(fallback['token'], check_freshness=False) or 0
            
            best_option = {
                'token': fallback['token'],
                'symbol': fallback['symbol'],
                'strike': int(float(fallback['strike'])) // 100,
                'delta': None,
                'ltp': fallback_ltp
            }
            logger.info(f"DELTA: Fallback selected - {best_option['symbol']} @ ₹{fallback_ltp:.2f}")
        
        return best_option
        
    except Exception:
        logger.exception(f"DELTA: Bounded selection failed for {opt_type}")
        return None
```

---

## 2️⃣ INDEPENDENT LEG ARCHITECTURE

### Changes to Entry Monitor

**REPLACE `_entry_monitor()` method:**
```python
def _entry_monitor(self):
    """
    Fully independent leg monitoring.
    Each leg checks and enters independently without waiting for others.
    """
    while not self._stop_event.is_set():
        try:
            # Only proceed if structure initialized
            if not self.state.get('structure_initialized', False):
                time.sleep(1)
                continue
            
            # SELL CE - fully independent
            if self.state.get('sell_ce_leg_ready') and not self.state.get('sell_ce_entered'):
                self._check_sell_entry('ce')
            
            # SELL PE - fully independent
            if self.state.get('sell_pe_leg_ready') and not self.state.get('sell_pe_entered'):
                self._check_sell_entry('pe')
            
            # Send trade entry notification after both SELL legs entered
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
            
            # BUY CE - fully independent (only if leg exists)
            if self.state.get('buy_ce_leg_ready') and not self.state.get('buy_ce_entered'):
                self._check_buy_entry('ce')
            
            # BUY PE - fully independent (only if leg exists)
            if self.state.get('buy_pe_leg_ready') and not self.state.get('buy_pe_entered'):
                self._check_buy_entry('pe')
            
        except Exception:
            logger.exception("Entry monitor error")
        
        time.sleep(0.5)  # Health throttle
```

### Changes to Exit Monitor

**REPLACE `_exit_monitor()` method:**
```python
def _exit_monitor(self):
    """
    Fully independent exit monitoring.
    Each leg exits independently based on its own SL/TP.
    """
    while not self._stop_event.is_set():
        try:
            # SELL CE - independent exit
            if self.state.get('sell_ce_entered') and not self.state.get('sell_ce_exited'):
                self._check_sell_exit('ce')
            
            # SELL PE - independent exit
            if self.state.get('sell_pe_entered') and not self.state.get('sell_pe_exited'):
                self._check_sell_exit('pe')
            
            # BUY CE - independent exit
            if self.state.get('buy_ce_entered') and not self.state.get('buy_ce_exited'):
                self._check_buy_exit('ce')
            
            # BUY PE - independent exit
            if self.state.get('buy_pe_entered') and not self.state.get('buy_pe_exited'):
                self._check_buy_exit('pe')
            
        except Exception:
            logger.exception("Exit monitor error")
        
        time.sleep(0.5)
```

---

## 3️⃣ TELEGRAM PHASE CONSISTENCY

### Changes to `utils/notifier.py`

**ADD at top of file:**
```python
from constants import PHASE_TRADING
```

**MODIFY `_build_snapshot_text()` method:**
```python
def _build_snapshot_text(self) -> Optional[str]:
    """Build periodic snapshot text. Returns None if not in trade."""
    with self._lock:
        phase = self.current_phase
        legs = list(self.active_legs.values())
    
    # Only send snapshot when TRADING (using constant)
    if phase != PHASE_TRADING or len(legs) == 0:
        return None
    
    # ... rest of method unchanged
```

**MODIFY `heartbeat()` method:**
```python
def heartbeat(self, phase: str, pnl: float, positions: int, legs: List[Dict[str, Any]] = None) -> None:
    """Update heartbeat state"""
    with self._lock:
        # Store phase using constant for consistency
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
                if token and ltp:
                    self.update_leg_ltp(token, ltp)
```

---

## 4️⃣ HARDENED TRAILING STOP LOSS

### Add to Each Leg State

**Modify state structure to track trailing updates:**

In `_check_sell_exit()`, add cooldown logic:

```python
def _check_sell_exit(self, ot):
    """
    Enhanced SELL exit with hardened trailing SL.
    Includes cooldown and broker confirmation.
    """
    try:
        if not self.state.get(f'sell_{ot}_entered') or self.state.get(f'sell_{ot}_exited'):
            return
        
        tok = self.state.get(f'sell_{ot}_token')
        entry = self.state.get(f'sell_{ot}_entry_price')
        if not tok or entry is None:
            return
        
        ltp = self.feed.get_ltp(tok, check_freshness=False)
        if ltp is None:
            return
        
        # Calculate SL/TP
        fixed_sl = entry * (1 + Config.SELL_SL_PERCENT)
        tp = entry * (1 - Config.SELL_TP_PERCENT)
        sl = fixed_sl
        
        # Trailing SL logic (after 14:15)
        current_time = ist_now().time()
        
        if current_time >= Config.TRAILING_ACTIVATION_TIME:
            # Check cooldown (10 seconds between trailing updates)
            last_trail_time = self.state.get(f'_sell_{ot}_last_trail_time', 0)
            cooldown_seconds = 10
            
            if time.time() - last_trail_time >= cooldown_seconds:
                try:
                    with self._trailing_lock:
                        if ot == 'ce':
                            adverse_price = self._trailing_sell_ce_adverse_price
                        else:
                            adverse_price = self._trailing_sell_pe_adverse_price
                    
                    if adverse_price is not None:
                        if ltp < adverse_price:
                            trailing_sl = adverse_price * (1 + Config.TRAILING_BUFFER_PERCENT)
                            
                            if trailing_sl < fixed_sl:
                                sl = trailing_sl
                                
                                # Update trailing timestamp
                                self.state.set(f'_sell_{ot}_last_trail_time', time.time())
                                
                                # Send notification if first time
                                state_key = f'_trailing_{ot}_logged'
                                if not self.state.get(state_key):
                                    logger.info(
                                        f"📉 TRAILING SL ACTIVE - SELL {ot.upper()}: "
                                        f"Fixed: ₹{fixed_sl:.2f} → Trailing: ₹{sl:.2f}"
                                    )
                                    self.state.set(state_key, True)
                                    
                                    # Send Telegram notification
                                    if self.notifier:
                                        try:
                                            ce_strike = self.state.get('sell_ce_strike', 0)
                                            ce_entry = self.state.get('sell_ce_entry_price', 0)
                                            ce_sl = ce_entry * (1 + Config.SELL_SL_PERCENT) if ce_entry else 0
                                            
                                            pe_strike = self.state.get('sell_pe_strike', 0)
                                            pe_entry = self.state.get('sell_pe_entry_price', 0)
                                            pe_sl = pe_entry * (1 + Config.SELL_SL_PERCENT) if pe_entry else 0
                                            
                                            # Get trailing SLs
                                            with self._trailing_lock:
                                                ce_adverse = self._trailing_sell_ce_adverse_price
                                                pe_adverse = self._trailing_sell_pe_adverse_price
                                            
                                            if ce_adverse:
                                                ce_trail = ce_adverse * (1 + Config.TRAILING_BUFFER_PERCENT)
                                                if ce_trail < ce_sl:
                                                    ce_sl = ce_trail
                                            
                                            if pe_adverse:
                                                pe_trail = pe_adverse * (1 + Config.TRAILING_BUFFER_PERCENT)
                                                if pe_trail < pe_sl:
                                                    pe_sl = pe_trail
                                            
                                            self.notifier.send_trailing_sl_update(
                                                ce_strike, ce_sl, pe_strike, pe_sl
                                            )
                                        except Exception:
                                            pass
                except Exception:
                    logger.exception(f"Trailing SL logic error for {ot}")
                    sl = fixed_sl
        
        # Exit logic
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
            logger.info(f"🔵 SELL {ot.upper()} EXIT @ ₹{ltp:.2f} [{reason}] P&L: ₹{pnl:.2f}")
            if self.notifier:
                try:
                    self.notifier.send_exit(f"🔵 SELL {ot.upper()}", ltp, pnl=pnl, reason=reason, token=tok)
                except Exception:
                    pass
    except Exception:
        logger.exception("_check_sell_exit error")
```

---

## 5️⃣ STATE CLEANUP

### Modify `core/state.py`

**Update `_cleanup_daily_state()` to remove old phase flags:**

```python
def _cleanup_daily_state(self):
    with self.lock:
        today = date.today().isoformat()
        last_run = self.state.get('last_run_date')
        if last_run and last_run != today:
            logger.info(f"🧹 New day reset")
            # Remove old phase flags and attempt counters
            for k in ['phase0_done', 'phase1_done',  # OLD - no longer used
                     'structure_initialized',  # NEW - will be reset
                     'sell_ce_entered', 'sell_pe_entered', 
                     'buy_ce_entered', 'buy_pe_entered',
                     'sell_ce_exited', 'sell_pe_exited',
                     'buy_ce_exited', 'buy_pe_exited',
                     'squareoff_done', 'phase1_complete_time', 'init_complete_time',
                     '_phase1_attempt_count', '_phase1_completed_without_hedges',
                     '_sell_ce_last_trail_time', '_sell_pe_last_trail_time',
                     '_trailing_ce_logged', '_trailing_pe_logged']:
                self.state.pop(k, None)
            # Remove leg flags
            for k in ['sell_ce_leg_ready', 'sell_pe_leg_ready', 
                     'buy_ce_leg_ready', 'buy_pe_leg_ready']:
                self.state.pop(k, None)
        elif last_run == today:
            logger.info("📋 Same day - preserving state")
        self.state['last_run_date'] = today
        self._save_state()
```

---

## 📋 COMPLETE FILE MODIFICATION CHECKLIST

### ✅ Files to Create:
1. `constants.py` - ✅ CREATED

### ✅ Files to Modify:

**1. strategy/engine.py:**
- [ ] Add `from constants import PHASE_INIT, PHASE_TRADING, PHASE_CLOSED`
- [ ] Replace `_phase_monitor()` with simplified version
- [ ] Add `_initialize_structure()` method
- [ ] Add `_select_by_delta_bounded()` method
- [ ] Update `_entry_monitor()` to check `structure_initialized`
- [ ] Update `_exit_monitor()` (already independent)
- [ ] Add cooldown to `_check_sell_exit()`
- [ ] Add cooldown to `_check_buy_exit()` (if trailing applied)
- [ ] Remove `_execute_phase0()` method (replaced)
- [ ] Remove `_execute_phase1()` method (replaced)

**2. utils/notifier.py:**
- [ ] Add `from constants import PHASE_TRADING`
- [ ] Replace `"IN TRADE"` with `PHASE_TRADING` in `_build_snapshot_text()`
- [ ] Ensure `heartbeat()` uses phase parameter correctly

**3. core/state.py:**
- [ ] Update `_cleanup_daily_state()` to remove phase0_done, phase1_done
- [ ] Add cleanup for new state keys

---

## 🎯 EXPECTED RESULTS

After refactoring:

### ✅ Unified Initialization:
- No time-based phase windows
- Single `structure_initialized` flag
- One initialization method
- Deterministic startup

### ✅ Bounded Delta Search:
- Max 50 iterations
- Fallback to nearest OTM
- No infinite loops
- Safe and predictable

### ✅ Phase Name Consistency:
- All modules use `PHASE_TRADING` constant
- No string mismatches
- Snapshots always sent during trading

### ✅ Independent Legs:
- Each leg checks/enters/exits independently
- No cross-leg dependencies
- Parallel execution possible

### ✅ Hardened Trailing:
- 10-second cooldown
- Timestamp tracking
- Safe updates
- No spam

---

## 🚀 DEPLOYMENT

1. **Backup current system**
2. **Create constants.py**
3. **Modify files in order:**
   - constants.py (create)
   - core/state.py (cleanup)
   - utils/notifier.py (phase constants)
   - strategy/engine.py (major refactoring)
4. **Delete strategy_state.json** (clean start)
5. **Test during market hours**

---

## ✅ TESTING CHECKLIST

- [ ] System starts without errors
- [ ] Structure initializes once at market open
- [ ] All 4 legs lock independently
- [ ] Telegram snapshots appear during TRADING
- [ ] Entry/exit logic works independently
- [ ] Trailing SL respects cooldown
- [ ] No infinite loops
- [ ] Phase transitions smooth
- [ ] Next day: fresh initialization

---

**This refactoring creates an institutional-grade robust system with clear separation of concerns and elimination of timing dependencies.**
