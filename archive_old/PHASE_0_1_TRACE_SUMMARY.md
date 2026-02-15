# PHASE 0/1 DEADLOCK DIAGNOSIS - EXECUTIVE SUMMARY

**Date:** February 15, 2026  
**Issue:** Phase 0/1 may deadlock or stall in StrategyEngine  
**Status:** DIAGNOSED - See detailed analysis below

---

## Q1: FLAGS CONTROLLING PHASE 0/1 TRANSITIONS

### Master Flag: `phase`
```
Possible values: STANDBY → PHASE0 → PHASE1 → IN_TRADE → CLOSED
Set by: _phase_monitor() based on current time
```

### Phase Completion Flags
| Flag | Purpose | How Set |
|------|---------|---------|
| `phase0_done` | Phase 0 complete | ✅ By `_execute_phase0()` after SELL CE + SELL PE locked |
| `phase1_done` | Phase 1 complete | ✅ By `_execute_phase1()` **ONLY if BOTH buy_ce_leg_ready AND buy_pe_leg_ready** |
| `_phase1_attempt_count` | Retry counter | Incremented each Phase 1 attempt |
| `_phase1_completed_without_hedges` | Max attempts reached | 🔴 Set when attempts ≥ CONFIG.PHASE1_MAX_ATTEMPTS |

### Per-Leg Status Flags
```
Stored in: trade_state = {
    'sell_ce': IDLE|READY|ENTERED|EXITED,
    'sell_pe': IDLE|READY|ENTERED|EXITED,
    'buy_ce':  IDLE|READY|ENTERED|EXITED,
    'buy_pe':  IDLE|READY|ENTERED|EXITED
}

Accessible as:
- sell_ce_leg_ready, sell_ce_entered, sell_ce_exited
- sell_pe_leg_ready, sell_pe_entered, sell_pe_exited
- buy_ce_leg_ready, buy_ce_entered, buy_ce_exited
- buy_pe_leg_ready, buy_pe_entered, buy_pe_exited
```

---

## Q2: FUNCTIONS READING PHASE FLAGS

### Phase Monitor (`_phase_monitor()`) - Lines 644-698
**When:** Every 1-3 seconds in dedicated thread

**Checks:**
- `phase0_done` → Execute Phase 0 if False during timewindow
- `phase1_done` → Execute Phase 1 if False during time window
- `phase` → Updates current phase value based on time

**Flow:**
```
if ct < PHASE0_START: phase = STANDBY
elif PHASE0_START <= ct < PHASE0_END:
    if not phase0_done: _execute_phase0()
elif PHASE1_START <= ct < PHASE1_END:
    if not phase1_done: _execute_phase1()
elif ct >= PHASE1_END:
    phase = IN_TRADE
```

### Phase 1 Loop (`_execute_phase1()`) - Lines 900-1000
**When:** Every 3 seconds (with throttle) during Phase 1 window

**Checks:**
- `phase1_done` → Early exit if already True
- `_phase1_attempt_count` → Increment and check vs MAX_ATTEMPTS
- `buy_ce_leg_ready` → Skip _select_by_delta if already locked
- `buy_pe_leg_ready` → Skip _select_by_delta if already locked

**Critical Gate:**
```
if buy_ce_leg_ready AND buy_pe_leg_ready:
    phase1_done = True  ← ONLY GATE FOR phase1_done
else:
    Keep _phase1_attempt_count < MAX_ATTEMPTS
    OR
    Force phase1_done = True (without hedges)
```

### Entry Monitor (`_entry_monitor()`) - Lines 1065+
**When:** Continuous loop (fast iteration)

**Checks per leg:**
```
if sell_ce_leg_ready and not sell_ce_entered:
    _check_sell_entry('ce')  ← Only runs if leg is READY

if sell_pe_leg_ready and not sell_pe_entered:
    _check_sell_entry('pe')

if buy_ce_leg_ready and not buy_ce_entered:
    _check_buy_entry('ce')

if buy_pe_leg_ready and not buy_pe_entered:
    _check_buy_entry('pe')
```

**🔴 CRITICAL:** Entry monitor does NOT wait for `phase1_done`
- Entries can proceed independently
- But will only attempt if leg is `ready`

---

## Q3: PER-LEG ACTIONS & _select_by_delta CALLS

### SELL CE (Phase 0)
```
_execute_phase0() [line 695]
  ├─ Get spot LTP
  ├─ Calculate ATM = round(spot_ltp)
  ├─ Calculate strike = ATM - SELL_CE_OFFSET
  ├─ Find option token
  ├─ Subscribe & get LTP
  └─ lock_sell_ce_leg(data)
       └─ Set: trade_state['sell_ce']='READY', sell_ce_leg_ready=True

Entry: if sell_ce_leg_ready and not sell_ce_entered → _check_sell_entry('ce')
Status: ✅ INDEPENDENT - Failure doesn't block SELL PE or Phase 0 done
```

### SELL PE (Phase 0)
```
_execute_phase0() [line 730]
  ├─ Use same ATM
  ├─ Calculate strike = ATM + SELL_PE_OFFSET
  ├─ Find option token
  ├─ Subscribe & get LTP
  └─ lock_sell_pe_leg(data)
       └─ Set: trade_state['sell_pe']='READY', sell_pe_leg_ready=True

Entry: if sell_pe_leg_ready and not sell_pe_entered → _check_sell_entry('pe')
Status: ✅ INDEPENDENT - Failure doesn't block SELL CE or Phase 0 done
```

### BUY CE (Phase 1)
```
_execute_phase1() [line 958]
  ├─ Check: if not buy_ce_leg_ready
  ├─ Find options in range: [ATM, ATM + DELTA_SCAN_RANGE]
  ├─ Subscribe & wait for deltas (4-20 seconds, 50% threshold)
  ├─ _select_by_delta(ATM, ATM+range, 'CE', expiry, TARGET_CE_DELTA)
  │   └─ Returns: {token, strike, delta, ltp} OR None
  ├─ if found: lock_buy_ce_leg(data)
  │   └─ Set: trade_state['buy_ce']='READY', buy_ce_leg_ready=True
  └─ Check gate: if buy_ce_leg_ready AND buy_pe_leg_ready → phase1_done=True

Entry: if buy_ce_leg_ready and not buy_ce_entered → _check_buy_entry('ce')
Status: 🔴 IF FAILS - Blocks phase1_done (retries until MAX_ATTEMPTS)
        Doesn't block BUY PE or entries (independent)
```

### BUY PE (Phase 1)
```
_execute_phase1() [line 968]
  ├─ Check: if not buy_pe_leg_ready
  ├─ Find options in range: [ATM - DELTA_SCAN_RANGE, ATM]
  ├─ Subscribe & wait for deltas (4-20 seconds, 50% threshold)
  ├─ _select_by_delta(ATM-range, ATM, 'PE', expiry, TARGET_PE_DELTA)
  │   └─ Returns: {token, strike, delta, ltp} OR None
  ├─ if found: lock_buy_pe_leg(data)
  │   └─ Set: trade_state['buy_pe']='READY', buy_pe_leg_ready=True
  └─ Check gate: if buy_ce_leg_ready AND buy_pe_leg_ready → phase1_done=True

Entry: if buy_pe_leg_ready and not buy_pe_entered → _check_buy_entry('pe')
Status: 🔴 IF FAILS - Blocks phase1_done (retries until MAX_ATTEMPTS)
        Doesn't block BUY CE or entries (independent)
```

---

## Q4: LEG DEPENDENCIES

### Independence Matrix
```
                SELL CE    SELL PE    BUY CE     BUY PE
SELL CE         -          ✅ Indep  ✅ Indep   ✅ Indep
SELL PE         ✅ Indep   -          ✅ Indep   ✅ Indep
BUY CE          ✅ Indep   ✅ Indep  -          🔴 GATE
BUY PE          ✅ Indep   ✅ Indep  🔴 GATE    -

Meaning:
- ✅ Indep: Failure of one doesn't block the other
- 🔴 GATE: BOTH must be ready for phase1_done to be True
```

### Critical Dependency: BUY CE ↔ BUY PE
```
phase1_done requires: buy_ce_leg_ready AND buy_pe_leg_ready

Scenario A: Both found
  → phase1_done = True ✅

Scenario B: BUY CE found, BUY PE fails
  → Keep retrying BUY PE
  → buy_ce_leg_ready = True, buy_pe_leg_ready = False
  → phase1_done = False (blocked)
  → Retry until MAX_ATTEMPTS
  → 🔴 DEADLOCK until timeout

Scenario C: Both fail
  → Keep retrying both
  → Both leg_ready = False
  → phase1_done = False (blocked)
  → Retry until MAX_ATTEMPTS
  → 🔴 DEADLOCK until timeout

Scenario D: Max attempts exceeded
  → phase1_done = True (forced, without hedges)
  → SELL legs can still enter
  → 🟡 RISK: No hedges available
```

### Cross-Phase Independence
```
SELL (Phase 0) ↔ BUY (Phase 1)
- ✅ FULLY INDEPENDENT
- Phase 0 completion doesn't depend on Phase 1
- SELL entries don't require BUY legs
- BUY entries don't require SELL legs
```

---

## Q5: BLOCKING POINTS PREVENTING LEG PROGRESS

### Blocking Point 1: _select_by_delta returns None
```
Impact: 🔴 That leg fails to lock
Cause: No options found OR all deltas don't match target
Duration: ~3 seconds (retry throttle)
Severity: MEDIUM - Retried each iteration until MAX_ATTEMPTS
```

### Blocking Point 2: Delta data unavailable
```
Impact: 🔴 _select_by_delta gets None delta values
Cause: Ticks not received, snapshot not updated
Duration: ~20 seconds (wait timeout)
Severity: MEDIUM - Timeout then retry
Config: PHASE1_DATA_WAIT_SECONDS, PHASE1_DATA_CHECK_INTERVAL
```

### Blocking Point 3: phase1_done remains False
```
Impact: 🔴 Phase phase value stays PHASE1 (doesn't move to IN_TRADE)
Cause: buy_pe_leg_ready != True while buy_ce_leg_ready = True
Duration: Until _phase1_attempt_count >= MAX_ATTEMPTS
Severity: 🔴 CRITICAL - Can persist for minutes (phase1_done forced)
```

### Blocking Point 4: MAX_ATTEMPTS exceeded
```
Impact: 🟡 phase1_done forced=True WITHOUT hedges
Cause: BUY legs couldn't be found within retry limit
Duration: End of Phase 1 window
Severity: 🔴 CRITICAL - Exposure without hedges
```

### Blocking Point 5: Safety validation fails
```
Impact: 🔴 Entire _entry_monitor loops - ALL legs blocked
Cause: Broker position mismatch, hard exit, leg independence violation
Duration: 5-30 seconds per failure
Severity: MEDIUM - Temporary, retried
Blocked: Sell entries, Buy entries (all 4 legs)
```

### Blocking Point 6: sell_*_leg_ready check fails
```
Impact: 🔴 THAT leg's entry check skipped
Cause: Leg not yet locked in Phase 0
Duration: Lifelong if Phase 0 fails
Severity: HIGH - No entry possible
Blocked: Single leg only
```

---

## Q6: RUNTIME PHASE/LEG TRACE FORMAT

### Snapshot Format (Human-Readable)
```
[STATE_SNAPSHOT] 07.45s
  Phase: PHASE1
  Phase 0: done=True
  Phase 1: done=False attempts=3 without_hedges=False
  SELL CE: ready=True entered=False
  SELL PE: ready=True entered=False
  BUY CE:  ready=True entered=False
  BUY PE:  ready=False entered=False
```

### Event Log Format
```
[PHASE_TRACE] ( 5.32s) EXECUTING_PHASE1: phase1_done=False, attempt 2, executing...
[PHASE_TRACE] ( 5.87s) SELECT_BY_DELTA_START: Type=PE, Range=[17700, 17900], Target_Delta=-0.3
[PHASE_TRACE] ( 6.14s) SELECT_BY_DELTA_FAILED: Type=PE - No option found in range
[PHASE_TRACE] ( 6.15s) PHASE1_ATTEMPT_RESULT: Attempt 2/50 - phase1_done=False, BUY_CE_ready=True, BUY_PE_ready=False, without_hedges=False
[PHASE_TRACE] ( 9.18s) EXECUTING_PHASE1: phase1_done=False, attempt 3, executing...
[PHASE_TRACE] ( 9.42s) SELECT_BY_DELTA_SUCCESS: Type=PE - Found: Strike=17850, Delta=-0.32, LTP=45.50
[STATE_SNAPSHOT] 10.00s
  Phase: PHASE1
  Phase 0: done=True
  Phase 1: done=True attempts=3 without_hedges=False
  SELL CE: ready=True entered=True
  SELL PE: ready=True entered=False
  BUY CE:  ready=True entered=False
  BUY PE:  ready=True entered=False
```

### Key Indicators

**✅ Healthy Phase 0:**
```
phase0_done=True, sell_ce_leg_ready=True, sell_pe_leg_ready=True (within 3-5 minutes)
```

**✅ Healthy Phase 1:**
```
phase1_done=True, buy_ce_leg_ready=True, buy_pe_leg_ready=True (within 15-20 minutes)
```

**🟡 Phase 1 Struggling:**
```
phase1_done=False, sell_ce_leg_ready=True, buy_ce_leg_ready=True, buy_pe_leg_ready=False
_phase1_attempt_count = 10-30 (increasing)
```

**🔴 DEADLOCK Imminent:**
```
phase1_done=False
buy_ce_leg_ready=True, buy_pe_leg_ready=False
_phase1_attempt_count >= 40 (approaching MAX_ATTEMPTS)
```

**🔴 DEADLOCK Forced Resolution:**
```
phase1_done=True
_phase1_completed_without_hedges=True
[This means phase1 forced done WITHOUT buy legs]
```

---

## CRITICAL FINDINGS

### Root Cause of Phase 0/1 Deadlock
1. **BUY PE can't find matching delta** - Returns None from _select_by_delta
2. **BUY CE already locked** - Skips its selection
3. **Phase 1 gate requires BOTH** - Waits for BUY PE
4. **BUY PE retries repeatedly** - Every 3 seconds
5. **Eventually forced to True** - After MAX_ATTEMPTS, without hedges

### Why This Happens
- **Delta mismatch:** Market deltas don't match Config.TARGET_PE_DELTA
- **Strike range incorrect:** DELTA_SCAN_RANGE doesn't include matching deltas
- **Time window too narrow:** Not enough time to find matching delta
- **Price movement:** Underlying moving too fast for selection

### Current Safeguards
✅ MAX_ATTEMPTS prevents infinite loop  
✅ Time window gate auto-moves phase at PHASE1_END  
✅ phase1_done forced True (allows SELL entries without hedges)  
❌ **NO GUARDRAIL** against unhedged entries

---

## HOW TO USE DIAGNOSTIC TOOLS

### 1. Generate Detailed Trace
```bash
python PHASE_0_1_TRACE.py
```
Outputs full event log with timestamps showing all phase/leg transitions

### 2. Review Diagnosis Document
See: [PHASE_0_1_DEADLOCK_DIAGNOSIS.md](PHASE_0_1_DEADLOCK_DIAGNOSIS.md)
Contains: Detailed code references, flow diagrams, scenario analysis

### 3. Monitor Live
Watch logs for patterns:
- If buy_pe_leg_ready stays False while buy_ce_leg_ready=True for >100 seconds
- If _phase1_attempts continuously increment without progress
- If phase1_done forced=True with without_hedges=True

---

## RECOMMENDATIONS

### Short-term (Immediate)
1. ✅ Monitor _phase1_attempt_count reaching 90% of MAX_ATTEMPTS
2. ✅ Alert if phase1_done forced without hedges
3. ✅ Log all _select_by_delta None returns with reason

### Medium-term (Next Update)
1. 🔄 Expand DELTA_SCAN_RANGE if market conditions change
2. 🔄 Make TARGET_*_DELTA dynamic based on market conditions
3. 🔄 Increase CONFIG.PHASE1_DATA_WAIT_SECONDS if deltas slow

### Long-term (Hardening)
1. 🔄 Implement hedge requirement check before SELL entries
2. 🔄 Add fallback delta targets (if primary fails)
3. 🔄 Block unhedged SELL entries with explicit config toggle
