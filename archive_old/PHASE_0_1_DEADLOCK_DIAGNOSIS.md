# PHASE 0/1 DEADLOCK DIAGNOSIS - ISSUE 4

**Date:** February 15, 2026  
**Status:** Diagnostic Analysis  
**Objective:** Map the Phase 0/1 deadlock path and identify blocking leg/flag combinations

---

## Q1: FLAGS CONTROLLING PHASE 0/1 TRANSITIONS

### Phase Transition Flow
```
STANDBY (ct < PHASE0_START)
  ↓
PHASE0 (PHASE0_START <= ct < PHASE0_END)
  ↓ [ when phase0_done=True ]
PHASE1 (PHASE1_START <= ct < PHASE1_END)
  ↓ [ when phase1_done=True ]
PHASE_IN_TRADE (ct >= PHASE1_END)
  ↓ [ when ct >= SQUAREOFF_TIME ]
CLOSED
```

### Critical Flags for Phase 0/1

| Flag | Purpose | Set By | Triggers |
|------|---------|--------|----------|
| `phase` | Current phase state | `set_phase()` | Phase monitor |
| `phase0_done` | Marks PHASE0 complete | `_execute_phase0()` | After SELL CE + SELL PE leg locks |
| `phase1_done` | Marks PHASE1 complete | `_execute_phase1()` | ONLY when BOTH buy_ce_leg_ready AND buy_pe_leg_ready |
| `_phase1_attempt_count` | Retry counter | `_execute_phase1()` | Incremented each attempt |
| `_phase1_completed_without_hedges` | Flag for max attempts reached | `_execute_phase1()` | Set when `_phase1_attempt_count >= MAX_ATTEMPTS` |
| `sell_ce_leg_ready` | SELL CE ready for entry | `lock_sell_ce_leg()` | Derived from `trade_state['sell_ce']='READY'` |
| `sell_pe_leg_ready` | SELL PE ready for entry | `lock_sell_pe_leg()` | Derived from `trade_state['sell_pe']='READY'` |
| `buy_ce_leg_ready` | BUY CE ready for entry | `lock_buy_ce_leg()` | Derived from `trade_state['buy_ce']='READY'` |
| `buy_pe_leg_ready` | BUY PE ready for entry | `lock_buy_pe_leg()` | Derived from `trade_state['buy_pe']='READY'` |

### Trade State (Single Source of Truth)
```json
{
  "trade_state": {
    "sell_ce": "IDLE|READY|ENTERED|EXITED",
    "sell_pe": "IDLE|READY|ENTERED|EXITED",
    "buy_ce": "IDLE|READY|ENTERED|EXITED",
    "buy_pe": "IDLE|READY|ENTERED|EXITED"
  }
}
```

---

## Q2: FUNCTIONS/METHODS READING FLAGS DURING RUNTIME

### Phase Monitor (`_phase_monitor()` - lines 644-698)
```python
# Reads or checks:
- self.state.get('phase0_done')      → Decides if to run PHASE0
- self.state.get('phase1_done')      → Decides if to run PHASE1
- self.state.get('phase')            → Current phase
- Time windows (ct < PHASE0_START, PHASE0_START <= ct < PHASE0_END, etc.)

# Key Decision Points:
if Config.PHASE0_START <= ct < Config.PHASE0_END:
    if not self.state.get('phase0_done'):
        → EXECUTE PHASE0
    
elif Config.PHASE1_START <= ct < Config.PHASE1_END:
    if not self.state.get('phase1_done'):
        → EXECUTE PHASE1
```

### Phase 1 Delta Selection (`_execute_phase1()` - lines 900-1000)
```python
# Critical checks:
- self.state.get('phase1_done')                → Early return if already done
- self.state.get('_phase1_attempt_count')      → Track retry attempts
- Config.PHASE1_MAX_ATTEMPTS                   → Abort if exceeded
- self.state.get('buy_ce_leg_ready')           → Skip if already locked
- self.state.get('buy_pe_leg_ready')           → Skip if already locked

# Critical decision:
if self.state.get('buy_ce_leg_ready') and self.state.get('buy_pe_leg_ready'):
    phase1_done = True  # ONLY WHEN BOTH READY
```

### Entry Checks (`_check_sell_entry()` and `_check_buy_entry()` - lines 1146-1305)
```python
# SELL CE Entry (line 1107):
if self.state.get('sell_ce_leg_ready') and not self.state.get('sell_ce_entered'):
    self._check_sell_entry('ce')

# SELL PE Entry (line 1111):
if self.state.get('sell_pe_leg_ready') and not self.state.get('sell_pe_entered'):
    self._check_sell_entry('pe')

# BUY CE Entry (line 1134):
if self.state.get('buy_ce_leg_ready') and not self.state.get('buy_ce_entered'):
    self._check_buy_entry('ce')

# BUY PE Entry (line 1138):
if self.state.get('buy_pe_leg_ready') and not self.state.get('buy_pe_entered'):
    self._check_buy_entry('pe')

# Each check ONLY runs if:
# 1. Leg is marked "ready" (locked in Phase 0/1)
# 2. Leg has NOT already entered
```

---

## Q3: PER-LEG ACTIONS - _select_by_delta CALLS AND LOCKING

### SELL CE Leg (Phase 0)
```
_execute_phase0()
  ├─ Find spot instrument
  ├─ Get spot LTP
  ├─ Calculate ATM strike
  ├─ Find SELL_CE_STRIKE = ATM - SELL_CE_OFFSET
  ├─ Find option token
  ├─ Subscribe to feed
  ├─ Get LTP
  └─ lock_sell_ce_leg(data)
       └─ Set: sell_ce_leg_ready=True, trade_state['sell_ce']='READY'

Triggered: During Config.PHASE0_START to Config.PHASE0_END
Entry Check: if sell_ce_leg_ready and not sell_ce_entered → _check_sell_entry('ce')
```

### SELL PE Leg (Phase 0)
```
_execute_phase0()
  ├─ Use same ATM
  ├─ Find SELL_PE_STRIKE = ATM + SELL_PE_OFFSET
  ├─ Find option token
  ├─ Subscribe to feed
  ├─ Get LTP
  └─ lock_sell_pe_leg(data)
       └─ Set: sell_pe_leg_ready=True, trade_state['sell_pe']='READY'

Triggered: During Config.PHASE0_START to Config.PHASE0_END
Entry Check: if sell_pe_leg_ready and not sell_pe_entered → _check_sell_entry('pe')
```

### BUY CE Leg (Phase 1)
```
_execute_phase1()
  ├─ Increment _phase1_attempt_count
  ├─ Check: if not buy_ce_leg_ready
  │    ├─ Get ATM (from Phase 0 or calculate independently)
  │    ├─ Find options in range: [ATM, ATM+DELTA_SCAN_RANGE*ATM_ROUND]
  │    ├─ Subscribe to feed
  │    ├─ Wait for delta data (50% ready or timeout)
  │    └─ _select_by_delta(ATM, ATM+range, 'CE', expiry, TARGET_CE_DELTA)
  │         └─ Find option with delta closest to TARGET_CE_DELTA
  │    └─ if found: lock_buy_ce_leg(data)
  │         └─ Set: buy_ce_leg_ready=True, trade_state['buy_ce']='READY'
  └─ Check: if buy_ce_leg_ready and buy_pe_leg_ready
       └─ Set phase1_done=True

Triggered: During Config.PHASE1_START to Config.PHASE1_END (multiple attempts)
Entry Check: if buy_ce_leg_ready and not buy_ce_entered → _check_buy_entry('ce')
```

### BUY PE Leg (Phase 1)
```
_execute_phase1()
  ├─ Check: if not buy_pe_leg_ready
  │    ├─ Get ATM (from Phase 0 or calculate independently)
  │    ├─ Find options in range: [ATM-DELTA_SCAN_RANGE*ATM_ROUND, ATM]
  │    ├─ Subscribe to feed
  │    ├─ Wait for delta data (50% ready or timeout)
  │    └─ _select_by_delta(ATM-range, ATM, 'PE', expiry, TARGET_PE_DELTA)
  │         └─ Find option with delta closest to TARGET_PE_DELTA
  │    └─ if found: lock_buy_pe_leg(data)
  │         └─ Set: buy_pe_leg_ready=True, trade_state['buy_pe']='READY'
  └─ Check: if buy_ce_leg_ready and buy_pe_leg_ready
       └─ Set phase1_done=True

Triggered: During Config.PHASE1_START to Config.PHASE1_END (multiple attempts)
Entry Check: if buy_pe_leg_ready and not buy_pe_entered → _check_buy_entry('pe')
```

---

## Q4: LEG DEPENDENCIES & BLOCKING

### Leg Independence Analysis

**SELL CE ↔ SELL PE (Phase 0)**
- ❌ **NO EXPLICIT DEPENDENCY** 
- Both locked in same _execute_phase0() call
- Both use same ATM calculation
- No flag prevents PE if CE fails
- ✅ **INDEPENDENT** - either leg failure doesn't block phase0_done

**BUY CE ↔ BUY PE (Phase 1)**
- 🔴 **GATE DEPENDENCY** 
- phase1_done requires BOTH to be locked
- Does NOT require them to be ENTERED
- If BUY CE locked but BUY PE fails repeatedly:
  - BUY PE attempts continue
  - phase1_done remains False
  - _phase1_attempt_count increases
  - At max attempts: phase1_done set to True WITHOUT buy legs

**SELL ↔ BUY (Cross-Phase)**
- **NO BLOCKING DEPENDENCY**
- PHASE0 completes independently of Phase 1
- SELL legs can enter even if BUY legs never lock
- BUY legs can enter independently

---

## Q5: POTENTIAL DEADLOCK SCENARIOS

### Deadlock Scenario A: BUY CE Locked, BUY PE Stuck
```
State:
  phase = PHASE1
  buy_ce_leg_ready = True
  buy_pe_leg_ready = False
  _phase1_attempt_count = 1,2,3...
  phase1_done = False

Behavior:
  - _execute_phase1() called repeatedly (every 3 seconds)
  - BUY CE: Skipped (already locked)
  - BUY PE: Attempts _select_by_delta() every iteration
  - If BUY PE cannot find matching delta:
    → Returns None
    → No lock occurs
    → Retry scheduled
  - Loop continues until _phase1_attempt_count >= MAX_ATTEMPTS
  - Then: phase1_done set to True (without buy legs)

Duration: Until MAX_ATTEMPTS reached (typically 30-50 seconds)
```

### Deadlock Scenario B: Neither BUY Leg Selects
```
State:
  phase = PHASE1
  buy_ce_leg_ready = False
  buy_pe_leg_ready = False
  _phase1_attempt_count = 1,2,3...
  phase1_done = False

Behavior:
  - _execute_phase1() called repeatedly
  - Both _select_by_delta() called each iteration
  - If delta data incomplete or strikes not found:
    → Both return None
    → No legs locked
    → Retry scheduled
  - Continues until MAX_ATTEMPTS reached
  - Then: phase1_done = True (without hedges)

Duration: Until MAX_ATTEMPTS reached
```

### Deadlock Scenario C: BUY legs found but delta mismatch
```
State:
  phase = PHASE1
  Options available but deltas don't match TARGET_*_DELTA
  _phase1_attempt_count increments

Behavior:
  - Options found and subscribed
  - Delta data received but all scores too high
  - best_option returns None
  - No lock occurs
  - Retry scheduled for next attempt

Duration: Until MAX_ATTEMPTS or price moves to correct delta
```

### Deadlock Scenario D: Entry Blocks Phase Transition
```
State:
  phase = PHASE1
  buy_ce_leg_ready = True
  buy_pe_leg_ready = True
  phase1_done = False (NOT SET!)

Potential Cause:
  - _execute_phase1() found both legs ready
  - But the phase1_done assignment didn't happen
  - OR: Entry monitor prevents phase1_done from being checked

Issue:
  - Phase stays in PHASE1 state
  - _execute_phase1() keeps running
  - No transition to PHASE_IN_TRADE
```

---

## Q6: BLOCKING POINTS PREVENTING LEG PROGRESS

### Critical Blocking Points

1. **_select_by_delta returns None**
   - 🔴 BLOCKS: That leg from locking
   - ✅ NO BLOCK to other legs
   - ✅ NO BLOCK to phase transitions
   - Retry scheduled: Every Config.PHASE1_RETRY_DELAY seconds

2. **_phase1_attempt_count >= MAX_ATTEMPTS**
   - 🔴 BLOCKS: Further retry attempts
   - ✅ Allows: phase1_done = True (without hedges)
   - ✅ Allows: Transition to PHASE_IN_TRADE
   - Critical: Prevents infinite loop

3. **phase1_done remains False**
   - 🔴 BLOCKS: Transition from PHASE1 to PHASE_IN_TRADE
   - ✅ But only blocks phase monitor's phase value update
   - ✅ Entry checks still run (they don't require phase1_done)
   - Impact: _entry_monitor() runs independently

4. **sell_*_leg_ready check fails in _entry_monitor**
   - 🔴 BLOCKS: THAT leg's entry check
   - ✅ NO BLOCK: Other legs
   - Cause: Leg not yet locked in Phase 0

5. **Safety validation fails**
   - 🔴 BLOCKS: All entry checks (entire _entry_monitor loops)
   - Examples:
     - Broker position reconciliation fail
     - Hard exit active
     - Leg independence violation
   - Impact: 5-second sleep before retry

---

## CRITICAL ISSUE: phase1_done and PHASE_IN_TRADE Transition

### The Gate
```python
# In _phase_monitor(), line 670-671:
elif Config.PHASE1_START <= ct < Config.PHASE1_END:
    if not self.state.get('phase1_done'):
        # Execute Phase 1 repeatedly
        self._execute_phase1()
    else:
        # Light throttle if done
        time.sleep(0.5)

# But transition to PHASE_IN_TRADE only happens when ct >= Config.PHASE1_END
elif ct >= Config.PHASE1_END and ct < Config.SQUAREOFF_TIME:
    if self.state.get('phase') != PHASE_IN_TRADE:
        self.set_phase(PHASE_IN_TRADE)
```

**Issue:** Phase 1 window has a TIME GATE, not a state gate
- If phase1_done never set, phase 1 keeps executing
- But once ct >= PHASE1_END, phase monitor moves to PHASE_IN_TRADE
- So this is NOT a deadlock - it auto-resolves at PHASE1_END time

---

## DIAGNOSIS SUMMARY

### Current State
✅ **SELL legs (Phase 0)**: Independent, no blocking
❌ **BUY legs (Phase 1)**: ONE must succeed for phase1_done
🔴 **Potential deadlock**: phase1_done never set if both BUY legs fail to find deltas

### Root Causes
1. **Delta mismatch**: Market deltas don't match Config.TARGET_*_DELTA
2. **Insufficient data**: Delta snapshots not available
3. **Timeout too short**: Not enough time to collect delta data
4. **Strike range wrong**: DELTA_SCAN_RANGE doesn't include matching deltas

### Current Safeguards
✅ MAX_ATTEMPTS limit prevents infinite loop
✅ Time window gate prevents permanent deadlock
✅ phase1_done can be True without hedges (at max attempts)
✅ Entry monitor runs independently of phase state

### Remaining Risk
🔴 **Hedge Loss Risk**: If phase1_done forces True without BUY legs
   - SELL legs still enter
   - No hedges available
   - Risk exposure increases

---

## RECOMMENDATIONS FOR TRACING

Run the diagnostic script: [PHASE_0_1_TRACE.py](./PHASE_0_1_TRACE.py)

The script will:
1. Log all flag state changes in real-time
2. Track _select_by_delta calls and results
3. Monitor lock_*_leg attempts with timestamps
4. Show phase transitions with flag dependencies
5. Alert on blocking conditions
6. Generate readable phase trace output
