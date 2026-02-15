# PHASE 0/1 DEADLOCK - VERIFICATION CHECKLIST

**Date:** February 15, 2026  
**Purpose:** Step-by-step checklist to verify and debug Phase 0/1 issues

---

## ✅ PRE-DEPLOYMENT CHECKLIST

### 1. Code Structure Review

- [ ] Verify `phase0_done` only set in `_execute_phase0()` after BOTH legs locked
- [ ] Verify `phase1_done` only set in `_execute_phase1()` when BOTH `buy_ce_leg_ready AND buy_pe_leg_ready` OR attempts maxed
- [ ] Verify `_phase1_attempt_count` increments every Phase1 attempt
- [ ] Verify `MAX_ATTEMPTS` config exists and is > 20
- [ ] Verify `_select_by_delta()` returns None when no delta match (doesn't crash)
- [ ] Verify `lock_*_leg()` methods actually set the `leg_ready` flag
- [ ] Verify entry checks read `leg_ready` flag before attempting entry
- [ ] Verify phase monitor doesn't block on `phase1_done` (time-based gate exists)

**How to check:**
```bash
# Search for phase1_done assignments
grep -n "phase1_done.*True" strategy/engine.py

# Should find exactly 2-3 places:
# 1. When both buy legs ready
# 2. When max attempts exceeded
# 3. Possibly initialization

# Verify AND gate
grep -n "buy_ce_leg_ready.*buy_pe_leg_ready" strategy/engine.py
```

### 2. Config Validation

- [ ] `PHASE1_MAX_ATTEMPTS` set to reasonable value (20-50, not 1-2)
- [ ] `PHASE1_RETRY_DELAY` > 0 (throttle exists)
- [ ] `PHASE1_DATA_WAIT_SECONDS` >= 10 (enough time for deltas)
- [ ] `TARGET_CE_DELTA` and `TARGET_PE_DELTA` are within market range (-1 to +1)
- [ ] `DELTA_SCAN_RANGE` is wide enough to find matching deltas

**How to check:**
```python
from config import Config
print(f"MAX_ATTEMPTS: {Config.PHASE1_MAX_ATTEMPTS}")
print(f"RETRY_DELAY: {Config.PHASE1_RETRY_DELAY}")
print(f"DATA_WAIT: {Config.PHASE1_DATA_WAIT_SECONDS}")
print(f"TARGET_CE_DELTA: {Config.TARGET_CE_DELTA}")
print(f"TARGET_PE_DELTA: {Config.TARGET_PE_DELTA}")
print(f"DELTA_SCAN_RANGE: {Config.DELTA_SCAN_RANGE}")
```

### 3. Logging Setup

- [ ] Verify logger configured to write to file
- [ ] Verify DEBUG_MODE can be enabled via environment variable
- [ ] Verify PHASE_TRACE log format includes timestamps

**How to check:**
```bash
# Test logging
python -c "
import os
os.environ['DEBUG_MODE']='true'
from utils.logger import logger
logger.info('Test log')
"
```

---

## 🧪 LIVE TEST CHECKLIST

### Test 1: Phase 0 Completes

**When:** Between 09:15-09:25 IST

**Steps:**
1. Start trading system: `python main.py`
2. Wait 2 minutes
3. Check logs for: `[OK] PHASE0: ATM=...`
4. Verify state file contains: `"phase0_done": true`
5. Verify both SELL leg_ready flags: `true`

**Expected output:**
```
[OK] PHASE0: ATM=17900, SELL CE=17800, PE=18000
[SELL_ENTRY_CHECK] SELL CE ref=45.50, ltp=45.30, decay=0.20, trigger=0.15, condition_met=False
[SELL_ENTRY_CHECK] SELL PE ref=51.20, ltp=51.00, decay=0.20, trigger=0.15, condition_met=False
```

**If fails:**
- [ ] Check "PHASE0: Spot LTP unavailable" → Feed not subscribing to spotindex="NIFTY-I"
- [ ] Check "PHASE0: Sell options not found" → Options contracts not in master instruments
- [ ] Check "PHASE0: No expiry found" → No expiry date available

**Verification command:**
```bash
# Check state file
grep -o '"phase0_done"' strategy_state.json
# Should output: "phase0_done": true
```

### Test 2: Phase 1 Completes (Success Path)

**When:** Between 09:25-14:15 IST (during Phase 1 window)

**Steps:**
1. Verify Phase 0 complete (from Test 1)
2. Wait 5 more minutes for Phase 1 to execute
3. Check logs for: `[OK] PHASE1: BUY CE locked at strike...`
4. Verify `[OK] PHASE1: BUY PE locked at strike...`
5. Verify: `[OK] PHASE1: Both BUY legs locked and ready`
6. Check state: `"phase1_done": true`
7. Verify `_phase1_attempt_count` is a small number (1-5)

**Expected output:**
```
PHASE1: Attempt 1/50
PHASE1: Subscribing to 24 options for delta calculation
PHASE1: Sufficient data received (12/24 options ready after 8.3s)
[OK] PHASE1: BUY CE locked at strike 17950
[OK] PHASE1: BUY PE locked at strike 17850
[OK] PHASE1: Both BUY legs locked and ready
```

**If fails:**
- [ ] Check "PHASE1: BUY CE not found" → Delta doesn't match TARGET_CE_DELTA, no option in range
- [ ] Check "PHASE1: BUY PE not found" → Same issue
- [ ] Check "PHASE1: Delta loop safety limit reached" → Timeout or retry limit exceeded

**Debug command:**
```python
# Check phase1_done
with open('strategy_state.json') as f:
    state = json.load(f)
    print(f"phase1_done: {state.get('phase1_done')}")
    print(f"attempts: {state.get('_phase1_attempt_count')}")
    print(f"without_hedges: {state.get('_phase1_completed_without_hedges')}")
```

### Test 3: Phase 1 Max Attempts (Failure Path)

**When:** If Phase 1 takes > 5 minutes to complete

**Steps:**
1. Monitor `_phase1_attempt_count` in logs
2. If count reaches >= 45 (out of 50):
   - [ ] Check logs for why _select_by_delta keeps returning None
   - [ ] Look for: `PHASE1: BUY CE/PE not found (attempt N/50)`
   - [ ] Note the delta values being sought: `Target_Delta=0.30`
   - [ ] Note available options: `SELECT_BY_DELTA_START`

3. Wait for final message: `PHASE1: Max attempts (50) reached - completing WITHOUT buy legs`
4. Verify: `"phase1_done": true` but `"buy_ce_leg_ready": false` or `"buy_pe_leg_ready": false`
5. Verify: `"_phase1_completed_without_hedges": true`

**Expected output (worst case):**
```
PHASE1: Attempt 40/50
PHASE1: BUY CE not found (attempt 40/50)
PHASE1: BUY PE not found (attempt 40/50)
...
PHASE1: Attempt 50/50
[WARN] PHASE1: Max attempts (50) reached - completing WITHOUT buy legs
[WARN] SELL legs will trade independently without hedges
```

**Critical check:**
```
🔴 AFTER THIS: SELL legs may enter WITHOUT protective BUY hedges
Alert to trader immediately
```

### Test 4: Entry Monitor (SELL Legs)

**When:** After Phase 0 complete, anytime during trading

**Steps:**
1. Monitor logs for: `[SELL_ENTRY_CHECK]`
2. Watch for: `ref=X.XX, ltp=Y.YY, decay=Z.ZZ, trigger=...`
3. When decay >= trigger, should see: `[OK] CONDITION MET - Placing order`
4. Verify order placed: `Order FILLED`
5. Check state: `"sell_ce_entered": true` (price matched condition)

**Expected sequence:**
```
[SELL_ENTRY_CHECK] SELL CE ref=45.50, ltp=45.40, decay=0.10, trigger=0.15, condition_met=False
[SELL_ENTRY_CHECK] SELL CE ref=45.50, ltp=45.20, decay=0.30, trigger=0.15, condition_met=True
[OK] CONDITION MET - Placing order: side=SELL, token=12345, qty=50, price=45.20
[OK] Order FILLED: {...}
SELL CE @ Rs45.20 - STATE UPDATED
```

### Test 5: Entry Monitor (BUY Legs)

**When:** After Phase 1 complete AND BUY legs ready

**Steps:**
1. Verify Phase 1 done and both BUY legs ready
2. Monitor logs for: `[BUY_ENTRY_CHECK]`
3. Watch for: `ref=X.XX, ltp=Y.YY, decay=Z.ZZ, trigger=...`
4. When decay >= trigger, should see: `[OK] CONDITION MET - Placing order`
5. Verify order placed: `Order FILLED`
6. Check state: `"buy_ce_entered": true` and `"buy_pe_entered": true`

**Expected sequence:**
```
[BUY_ENTRY_CHECK] BUY CE ref=45.20, ltp=45.30, decay=-0.10, trigger=0.15, condition_met=False
[BUY_ENTRY_CHECK] BUY CE ref=45.20, ltp=45.50, decay=-0.30, trigger=0.15, condition_met=True
[OK] CONDITION MET - Placing order: side=BUY, token=12346, qty=50, price=45.50
[OK] Order FILLED: {...}
BUY CE @ Rs45.50 - STATE UPDATED
```

---

## 🔍 DEBUGGING CHECKLIST

### If Phase 0 Won't Complete

**Symptom:** `phase0_done=False` after 5+ minutes

```
Check 1: Spot subscribed?
  grep -n "spot_token\|Spot instrument" logs/
  Should show: "PHASE0: spot_token=..." or "Found: NIFTY-I"

Check 2: Spot LTP available?
  grep -n "spot_ltp\|Spot LTP" logs/
  Should show: "spot_ltp=17850" (actual value, not None)

Check 3: Option contracts found?
  grep -n "find_option.*SELL\|sell_ce\|sell_pe" logs/
  Should show tokens and symbols for both CE and PE

Check 4: Options subscribed and LTP available?
  grep -n "subscribe.*token\|get_ltp" logs/
  Should show subscription confirmations

Action:
  - [ ] Check master instruments CSV has NIFTY options
  - [ ] Check broker API returning data
  - [ ] Check subscription succeeding in feed
```

### If Phase 1 Stalls (Doesn't find BUY legs)

**Symptom:** `_phase1_attempt_count=10+` but `phase1_done=False`

```
Check 1: CE selection attempts
  grep -n "SELECT_BY_DELTA.*CE\|BUY CE" logs/
  Should show successful selections alternating with failures

Check 2: PE selection attempts
  grep -n "SELECT_BY_DELTA.*PE\|BUY PE" logs/
  Should show successful selections alternating with failures

Check 3: Deltas being calculated?
  grep -n "delta\|Delta" logs/
  Should show delta values being received from broker

Check 4: If deltas missing
  grep -n "get_snapshot\|delta.*None" logs/
  Indicates snapshots not updated with delta data
  Cause: Broker not sending delta, or snapshot not refreshing

Action:
  - [ ] Check broker returning delta in snapshot
  - [ ] Check instrument snapshot being updated
  - [ ] Expand DELTA_SCAN_RANGE in config
  - [ ] Relax TARGET_*_DELTA values
  - [ ] Increase PHASE1_DATA_WAIT_SECONDS
```

### If Entry Conditions Never Met

**Symptom:** `condition_met=False` repeatedly

```
Check 1: Leg ready?
  grep -n "leg_ready=\|leg_ready:" logs/
  Should show: "leg_ready=True" for attempted leg

Check 2: Decay calculation
  grep -n "decay=.*trigger=" logs/
  Example: decay=0.10, trigger=0.15 → condition_met=False
  Meaning: Price hasn't fallen enough (SELL) or risen enough (BUY)

Check 3: LTP being fetched?
  grep -n "ltp=\|LTP" logs/
  Should show current prices being read

Action:
  - [ ] Check *_ref_premium set correctly (reference price at lock time)
  - [ ] Check SELL_DECAY_TRIGGER reasonable (0.10-0.30 typical)
  - [ ] Check BUY_DECAY_TRIGGER reasonable (0.10-0.30 typical)
  - [ ] Check market is moving enough
  - [ ] Check time window (entries only during PHASE_IN_TRADE)
```

---

## 🚨 EMERGENCY DIAGNOSTICS

### Live System Hung?

```python
# SSH into server or use Python REPL
import json

# Load current state
with open('strategy_state.json') as f:
    state = json.load(f)

# Quick health check
print("=== PHASE HEALTH ===")
print(f"Phase: {state.get('phase')}")
print(f"Phase 0: {state.get('phase0_done')}")
print(f"Phase 1: {state.get('phase1_done')}")
print(f"Phase 1 Attempts: {state.get('_phase1_attempt_count', 0)}")

print("\n=== LEG READINESS ===")
print(f"SELL CE: ready={state.get('sell_ce_leg_ready')} entered={state.get('sell_ce_entered')}")
print(f"SELL PE: ready={state.get('sell_pe_leg_ready')} entered={state.get('sell_pe_entered')}")
print(f"BUY CE:  ready={state.get('buy_ce_leg_ready')} entered={state.get('buy_ce_entered')}")
print(f"BUY PE:  ready={state.get('buy_pe_leg_ready')} entered={state.get('buy_pe_entered')}")

print("\n=== RISK ===")
if state.get('_phase1_completed_without_hedges'):
    print("🔴 UNHEDGED ENTRIES: phase1 forced without buy legs")
if state.get('sell_ce_entered') and not state.get('buy_ce_leg_ready'):
    print("🔴 SELL CE entered but BUY CE not ready")
if state.get('sell_pe_entered') and not state.get('buy_pe_leg_ready'):
    print("🔴 SELL PE entered but BUY PE not ready")
```

### Check Recent Logs

```bash
# Last 50 lines of main log
tail -50 logs/$(date +%Y-%m-%d)/engine.log

# Search for errors
grep -i "error\|exception" logs/$(date +%Y-%m-%d)/engine.log | tail -20

# Search for phase transitions
grep "PHASE0\|PHASE1\|phase0_done\|phase1_done" logs/$(date +%Y-%m-%d)/engine.log

# Count phase1 attempts
grep -o "_phase1_attempt_count" logs/$(date +%Y-%m-%d)/engine.log | wc -l
```

---

## ✅ RECOVERY STEPS

### If Phase 1 Forced Without Hedges

**Action:** Manual entry block or hedge placement

```python
# Option 1: Block SELL entries entirely
state.set('hard_exit_no_new_entries', True)
state.set('trade_closed', True)

# Option 2: Manual hedge entry (if broker API available)
# Place BUY CE at closest available delta
# Place BUY PE at closest available delta

# Option 3: Close SELL position immediately
# Execute sell-to-close orders for entered SELL legs
```

### If Phase Stalls In Window

**Action:** Force transition by time or manual override

```python
# Option 1: Update state to next phase
state.set('phase1_done', True)
# System will move to PHASE_IN_TRADE at time gate

# Option 2: Manual reset for next day
state.set('phase0_done', False)
state.set('phase1_done', False)
state.set('_phase1_attempt_count', 0)
state.set('_phase1_completed_without_hedges', False)
```

---

## 📊 SUCCESS METRICS

**Phase 0 Healthy:** Complete in < 5 minutes  
**Phase 1 Healthy:** Complete in < 15 minutes with both legs ready  
**Phase 1 Max:** If reaching > 40 attempts, investigate next day  
**Entries Healthy:** All 4 legs should have entries by 11:30 IST  
**Hedges Present:** Buy legs MUST be ready before sell entries execute  

---

## 📝 NOTES FOR NEXT DEBUGGING SESSION

Add any observations here about Phase 0/1 issues encountered:

```
Date: ___________
Issue: ___________
Symptom: ___________
Root Cause Found: ___________
Fix Applied: ___________
```
