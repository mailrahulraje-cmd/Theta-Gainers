# PHASE 0/1 DEADLOCK - VISUAL DEPENDENCY MAP

**Date:** February 15, 2026  
**Purpose:** Quick visual reference for Phase 0/1 flag dependencies and blocking points

---

## STATE FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PHASE MONITOR LOOP (1-3s intervals)             │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ↓             ↓             ↓
        ┌───────────────────┐ 
        │ Time Gate Check   │
        │ ct < PHASE0_START │ ──→ phase = STANDBY
        └───────────────────┘

        ┌───────────────────────────────────────────┐
        │ PHASE0_START ≤ ct < PHASE0_END            │
        │ Check: phase0_done?                        │
        └───────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
    NO  ↓                       ↓ YES
   Execute              Skip (already done)
   Phase 0              Light throttle


    ┌──────────────────────────────────────────────┐
    │      EXECUTE PHASE 0 (one-time)            │
    │  ┌────────────────┐  ┌────────────────┐   │
    │  │ Find SELL_CE   │  │ Find SELL_PE   │   │
    │  │ Subscribe feed │  │ Subscribe feed │   │
    │  │ lock_leg()     │  │ lock_leg()     │   │
    │  └────────────────┘  └────────────────┘   │
    │         │                    │             │
    │         ✅ Sets:             ✅ Sets:      │
    │         sell_ce_leg_ready   sell_pe_leg_ready
    │         trade_state=READY   trade_state=READY
    │         │                    │             │
    │         └────────┬───────────┘             │
    │                  ↓                         │
    │         phase0_done = True                │
    └──────────────────────────────────────────────┘
                       │
                       ↓
        ┌──────────────────────────────┐
        │ PHASE1_START ≤ ct < PHASE1_END
        │ Check: phase1_done?           │
        └──────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
    NO  ↓                       ↓ YES
   Execute              Skip (already done)
   Phase 1              Light throttle
            

    ┌──────────────────────────────────────────────┐
    │   EXECUTE PHASE 1 (repeated, with retry)    │
    │ Increment _phase1_attempt_count              │
    │                                              │
    │  ┌─────────────────┐  ┌─────────────────┐  │
    │  │ Buy_CE_Ready?   │  │ Buy_PE_Ready?   │  │
    │  └─────────────────┘  └─────────────────┘  │
    │        │                      │             │
    │  NO:↓ _select_by_delta  NO:↓ _select_by_delta
    │  YES: Skip (locked)     YES: Skip (locked)  │
    │        │                      │             │
    │  ✅ or None             ✅ or None          │
    │        │                      │             │
    │  lock_buy_ce_leg()     lock_buy_pe_leg()   │
    │        │                      │             │
    │  buy_ce_leg_ready=T    buy_pe_leg_ready=T  │
    │                                              │
    │  ┌──────────────────────────────────────┐  │
    │  │ GATE CHECK:                           │  │
    │  │ if buy_ce_leg_ready AND              │  │
    │  │    buy_pe_leg_ready:                 │  │
    │  │   phase1_done = True ✅              │  │
    │  │ else if attempts >= MAX_ATTEMPTS:    │  │
    │  │   phase1_done = True (no hedges) 🔴 │  │
    │  └──────────────────────────────────────┘  │
    │                                              │
    │  Retry throttle: 3 seconds                  │
    └──────────────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ↓                             ↓
   ✅ Phase1_done=T         🔴 Phase1_done=F
   Phase → IN_TRADE          Retry again
                              (loop)
```

---

## FLAG DEPENDENCY TREE

```
root: phase  (STANDBY → PHASE0 → PHASE1 → IN_TRADE → CLOSED)
│
├─ phase0_done
│  └─ [GATED BY] sell_ce_leg_ready ✅ AND sell_pe_leg_ready ✅
│     │
│     ├─ sell_ce_leg_ready
│     │  └─ [SET BY] lock_sell_ce_leg() in _execute_phase0()
│     │     └─ [DEPENDS] find_option() + feed subscribe
│     │
│     └─ sell_pe_leg_ready
│        └─ [SET BY] lock_sell_pe_leg() in _execute_phase0()
│           └─ [DEPENDS] find_option() + feed subscribe
│
├─ phase1_done  ← 🔴 CRITICAL GATE
│  └─ [GATED BY] buy_ce_leg_ready ✅ AND buy_pe_leg_ready ✅
│     │
│     ├─ buy_ce_leg_ready
│     │  └─ [SET BY] lock_buy_ce_leg() in _execute_phase1()
│     │     └─ [DEPENDS] _select_by_delta() returns non-None
│     │        └─ [DEPENDS] delta snapshots available
│     │           └─ [DEPENDS] feed ticks arriving
│     │
│     ├─ buy_pe_leg_ready
│     │  └─ [SET BY] lock_buy_pe_leg() in _execute_phase1()
│     │     └─ [DEPENDS] _select_by_delta() returns non-None
│     │        └─ [DEPENDS] delta snapshots available
│     │           └─ [DEPENDS] feed ticks arriving
│     │
│     └─ [OR] _phase1_attempt_count >= MAX_ATTEMPTS
│        └─ Force: phase1_done=True (without hedges) 🔴
│
└─ _phase1_attempt_count
   └─ [INCREMENTED] Every _execute_phase1() call
      └─ [THROTTLED] 3 seconds between calls
```

---

## BLOCKING CHAIN ANALYSIS

### Scenario: Buy PE Cannot Find Delta

```
Time |  Phase Monitor            | Phase 1 Loop              | Entry Monitor
─────┼──────────────────────────┼──────────────────────────┼──────────────────
 00s | PHASE0 window open        |                          |
     | phase0_done? NO           |                          |
     | Execute Phase 0 ──┐       |                          |
     |                   |       |                          |
 05s |                   └─→ phase0_done=True              |
     |                      sell_ce_leg_ready=T            |
     |                      sell_pe_leg_ready=T            |
     |                                                      | Check SELL CE
     |                                                      | sell_ce_leg_ready? ✅
     |                                                      | Enter! ✅
     |                                                      |
 15s | PHASE1 window open        |                          |
     | phase1_done? NO           |                          |
     | Execute Phase 1 ──┐       |                          |
     |                   └─→ _phase1_attempt_count=1        |
     |                      _select_by_delta(CE) ──→ ✅    |
     |                      buy_ce_leg_ready=T              |
     |                      _select_by_delta(PE) ──→ None   |
     |                      buy_pe_leg_ready=F              |
     |                      phase1_done? (T AND F)=F        |
     |                      Return, wait 3 seconds          |
     |                                                      | Check BUY CE
     |                                                      | buy_ce_leg_ready? ✅
     |                                                      | Enter! ✅
     |                                                      |
 18s |                          | _phase1_attempt_count=2   |
     |                          | _select_by_delta(CE) ──→ Already locked, skip
     |                          | _select_by_delta(PE) ──→ None
     |                          | buy_pe_leg_ready=F        |
     |                          | phase1_done? F            |
     |
[... repeats every 3 seconds ...]
     |
 40s |                          | _phase1_attempt_count=9   |
     |                          | _select_by_delta(PE) ──→ Now ✅ (price moved!)
     |                          | buy_pe_leg_ready=T        |
     |                          | phase1_done? (T AND T)=T ✅
     |                                                      | Check BUY PE
     |                                                      | buy_pe_leg_ready? ✅
     |                                                      | Enter! ✅
     |
 50s | PHASE1 window now done   |                          |
     | phase1_done=T            |                          |
     | → IN_TRADE window        |                          |
     | phase = PHASE_IN_TRADE   |                          |
```

### Scenario: Max Attempts Reached

```
Time |  Phase Monitor            | Phase 1 Loop              | Entry Monitor
─────┼──────────────────────────┼──────────────────────────┼──────────────────
 15s | PHASE1 window open        |                          |
     | phase1_done? NO           |                          |
     | Execute Phase 1 ──┐       |                          |
     |                   └─→ _phase1_attempt_count=1        |
     |                      _select_by_delta(PE) ──→ None   |
     |                      buy_pe_leg_ready=F              |
     |
[... repeats ...]
     |
 50s | Still in PHASE1 window    | _phase1_attempt_count=12 |
     | phase1_done? NO           | _select_by_delta(PE)     |
     | Execute Phase 1 ──┐       | ──→ Still None           |
     |                   └─→ buy_ce_leg_ready=T             |
     |                      buy_pe_leg_ready=F              |
     |                      phase1_done? F (blocked)        |
     |                                                      | WAITING
     |                                                      | buy_pe_leg_ready=F
     |                                                      | Can't enter PE ❌
     |
[... continues ...]
     |
120s | PHASE1 window open        | _phase1_attempt_count=41 |
     | phase1_done? NO           | attempts >= MAX_ATTEMPTS!|
     | Execute Phase 1 ──┐       | 🔴 Force:               |
     |                   └─→ phase1_done=True (FORCED)     |
     |                      _phase1_completed_without_hedges=True
     |                      WITHOUT buy_pe_leg_ready! 🔴   |
     |                                                      | Exit monitoring
     |                                                      | BUY PE still can't
     |                                                      | enter (not ready)
     |
```

---

## QUICK REFERENCE: IDENTIFYING DEADLOCK

### Checkpoint 1: Phase 0 Progress
Run this check at **5 minutes into market open:**

```
✅ HEALTHY:
   phase0_done=True
   sell_ce_leg_ready=True ✅
   sell_pe_leg_ready=True ✅

❌ PROBLEM:
   phase0_done=False
   OR Any leg_ready=False
   → Phase 0 failed, check logs for PHASE0 errors
```

### Checkpoint 2: Phase 1 Progress
Run this check at **20 minutes into market open:**

```
✅ HEALTHY:
   phase1_done=True
   buy_ce_leg_ready=True ✅
   buy_pe_leg_ready=True ✅

🟡 STRUGGLING:
   phase1_done=False
   _phase1_attempt_count=5-20
   One leg_ready=True, other=False
   → Phase 1 retrying, monitor
   
🔴 DEADLOCK:
   phase1_done=False
   _phase1_attempt_count >= 35
   buy_ce_leg_ready=True
   buy_pe_leg_ready=False
   → Imminent forced resolution without hedges
```

### Checkpoint 3: Entry Status
Continuous check **20+ minutes into market:**

```
✅ HEALTHY:
   sell_ce_entered=True ✅
   sell_pe_entered=True ✅
   buy_ce_leg_ready=True ✅ (or entered=True)
   buy_pe_leg_ready=True ✅ (or entered=True)

🟡 RISK:
   sell_ce_entered=True
   sell_pe_entered=True
   buy_ce_leg_ready=False
   buy_pe_leg_ready=False
   → Unhedged! Check phase1_completed_without_hedges

🔴 CRITICAL:
   phase1_completed_without_hedges=True
   → All SELL legs entered WITHOUT BUY leg hedges
   → Emergency monitoring required
```

---

## STATE DUMP EXTRACTION

When debugging, extract key state using:

```python
# From logs or live state
state = {
    'phase': engine.state.get('phase'),
    'phase0_done': engine.state.get('phase0_done'),
    'phase1_done': engine.state.get('phase1_done'),
    '_phase1_attempt_count': engine.state.get('_phase1_attempt_count'),
    '_phase1_completed_without_hedges': engine.state.get('_phase1_completed_without_hedges'),
    
    # Per-leg
    'sell_ce_leg_ready': engine.state.get('sell_ce_leg_ready'),
    'sell_ce_entered': engine.state.get('sell_ce_entered'),
    'sell_pe_leg_ready': engine.state.get('sell_pe_leg_ready'),
    'sell_pe_entered': engine.state.get('sell_pe_entered'),
    'buy_ce_leg_ready': engine.state.get('buy_ce_leg_ready'),
    'buy_ce_entered': engine.state.get('buy_ce_entered'),
    'buy_pe_leg_ready': engine.state.get('buy_pe_leg_ready'),
    'buy_pe_entered': engine.state.get('buy_pe_entered'),
}

# Or from trade_state directly
trade_state = engine.state.get('trade_state', {})
```

---

## MEMORY JOGGER: THE 6-POINT ANALYSIS

| Q | Answer |
|---|--------|
| **Q1: Flags?** | `phase`, `phase0_done`, `phase1_done`, `_phase1_attempt_count`, 4 leg_ready flags, 4 entered flags |
| **Q2: Functions?** | `_phase_monitor()`, `_execute_phase0()`, `_execute_phase1()`, `_check_sell_entry()`, `_check_buy_entry()` |
| **Q3: Per-leg?** | SELL: lock via Phase0. BUY: _select_by_delta → lock via Phase1 (repeat until found) |
| **Q4: Dependencies?** | SELL ↔ SELL: Independent. BUY ↔ BUY: 🔴 BOTH required for phase1_done. SELL ↔ BUY: Independent |
| **Q5: Blocks?** | _select_by_delta=None, delta_unavailable, phase1_done=False, safety_fail, leg_not_ready |
| **Q6: Trace?** | Log format: timestamps + phase changes + leg status. Watch _phase1_attempt_count and phase1_done |

---

## CONFIG PARAMETERS AFFECTING DEADLOCK

| Config | Default | Impact |
|--------|---------|--------|
| `PHASE0_START`, `PHASE0_END` | 09:15-09:25 | Phase 0 window |
| `PHASE1_START`, `PHASE1_END` | 09:25-14:15 | Phase 1 window |
| `PHASE1_MAX_ATTEMPTS` | 50 | Max retries before forcing phase1_done |
| `PHASE1_RETRY_DELAY` | 3.0s | Throttle between Phase1 attempts |
| `PHASE1_DATA_WAIT_SECONDS` | 20 | Max wait for deltas |
| `TARGET_CE_DELTA`, `TARGET_PE_DELTA` | 0.3, -0.3 | Delta targets for BUY legs |
| `DELTA_SCAN_RANGE` | 2 | Price range to scan for deltas (in ATM_ROUND units) |
| `DELTA_LOOP_MAX_RETRIES` | 30 | Safety check on delta loop |
| `DELTA_LOOP_TIMEOUT` | 600s | Timeout for entire delta selection |

Tuning these can prevent deadlock in different market conditions.
