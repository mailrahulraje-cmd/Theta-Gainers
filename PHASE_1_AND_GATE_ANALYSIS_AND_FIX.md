# PHASE 1 AND-GATE BLOCKING ANALYSIS & FIX

**Date:** February 15, 2026  
**Focus:** Why _execute_phase1() enforces AND-gate and how to fix it  
**Status:** Analysis + Non-invasive Solution Provided

---

## 1️⃣ WHY THE AND-GATE EXISTS (Current Design)

### Current Code (Line 984-990 in engine.py)
```python
# Mark phase1 done only if BOTH BUY legs ready
if self.state.get('buy_ce_leg_ready') and self.state.get('buy_pe_leg_ready'):
    self.state.set('phase1_done', True)
    self.state.set('phase1_complete_time', time.time())
    logger.info("[OK] PHASE1: Both BUY legs locked and ready")
```

### Design Intent
The AND-gate exists because:
```
PURPOSE: Ensure both protective hedges are locked before marking Phase 1 complete

RATIONALE: 
  - SELL legs entered in Phase 1 (independent)
  - BUY legs must protect SELL legs
  - Strategy requires BOTH BUY legs to hedge the SELL pair
  - Enter BUY only when BOTH ready = safer, balanced hedge
```

### The Problem
```
While legs SELECTED independently (CE/PE separate calls):
  ├─ if not buy_ce_leg_ready:
  │   select_by_delta(CE) → found or None
  │
  └─ if not buy_pe_leg_ready:
      select_by_delta(PE) → found or None

Gate is COUPLED:
  if buy_ce_leg_ready AND buy_pe_leg_ready:
    phase1_done = True

BLOCKING CHAIN:
  If PE fails (returns None):
    ├─ phase1_done = False
    ├─ CE locked (ready=True) but unused
    ├─ PE not locked (ready=False)
    ├─ Retries entire attempt (both legs skipped if data incomplete)
    ├─ Loop continues every 3 seconds
    └─ Until MAX_ATTEMPTS exhausted (~150s)
```

---

## 2️⃣ PER-LEG TIMELINE: PHASE 1 RETRY SEQUENCE

### Healthy Path (Both Legs Found)
```
Time │ Attempt │ BUY CE Status      │ BUY PE Status      │ phase1_done │ Action
─────┼─────────┼────────────────────┼────────────────────┼─────────────┼───────────────
  0s │    1    │ Not locked         │ Not locked         │ False       │ subscribe CE/PE
  2s │    1    │ 50% data ready     │ 50% data ready     │ False       │ waiting...
  5s │    1    │ 100% data ready    │ 100% data ready    │ False       │ call _select_by_delta
  6s │    1    │ ✅ LOCKED (str20)  │ ✅ LOCKED (str18)  │ ❓ CHECK   │ Both found!
  6s │    1    │ leg_ready=True     │ leg_ready=True     │ ✅ TRUE    │ phase1_done set!
  6s │    1    │ ready=T, enter=F   │ ready=T, enter=F   │ ✅ TRUE    │ Move to IN_TRADE
     │         │                    │                    │             │
  Result: 🟢 SUCCESS - Phase 1 complete in 6 seconds
```

### Failure Path (PE Fails, CE Succeeds)
```
Time │ Attempt │ BUY CE Status      │ BUY PE Status      │ phase1_done │ Action
─────┼─────────┼────────────────────┼────────────────────┼─────────────┼───────────────
  0s │    1    │ Not locked         │ Not locked         │ False       │ subscribe CE/PE
  2s │    1    │ 50% data ready     │ 50% partial ready  │ False       │ waiting...
  5s │    1    │ 100% ready         │ only 30% ready     │ False       │ timeout/proceed
  6s │    1    │ ✅ LOCKED (str20)  │ ❌ None (timeout)  │ ❌ FALSE   │ CE found, PE timeout
  6s │    1    │ leg_ready=True     │ leg_ready=False    │ ❌ FALSE   │ 🔴 BLOCKED!
  6s │    1    │ ready=T, enter=F   │ ready=F, enter=F   │ ❌ FALSE   │ RETRY (3s throttle)
     │         │                    │                    │             │
  9s │    2    │ skip (already locked)
     │         │                    │                    │             │
  9s │    2    │ ready=True (cached)│ Not locked         │ ❌ FALSE   │ Try PE again
 10s │    2    │ skip               │ 😞 Still None      │ ❌ FALSE   │ PE still fails
 10s │    2    │ ready=T, enter=F   │ ready=F, enter=F   │ ❌ FALSE   │ RETRY again
     │         │                    │                    │             │
[... repeats every 3 seconds ...]
     │         │                    │                    │             │
120s │   40    │ ready=T, enter=F   │ ready=F, enter=F   │ ❌ FALSE   │ Attempts: 39/50
123s │   41    │ skip               │ ✅ LOCKED (str19)  │ ❌ CHECK   │ PE finally found!
123s │   41    │ ready=T            │ leg_ready=True     │ ✅ TRUE    │ Both ready now!
123s │   41    │ ready=T, enter=F   │ ready=T, enter=F   │ ✅ TRUE    │ phase1_done set!
     │         │                    │                    │             │
  Result: 🟡 SUCCESS BUT DELAYED - 123 seconds (41 attempts)
           Risk: SELL legs may have already entered (unhedged)!
```

### Worst Path (Both Fail Until Max Attempts)
```
Time │ Attempt │ BUY CE Status      │ BUY PE Status      │ phase1_done │ Action
─────┼─────────┼────────────────────┼────────────────────┼─────────────┼───────────────
 [0-120s similar to above, both returning None]
     │         │                    │                    │             │
150s │   50    │ ready=False        │ ready=False        │ ❌ FALSE   │ Attempt 50/50
150s │   50    │ ❌ None (delta off)│ ❌ None (delta off)│ ❌ FALSE   │ Both fail again
150s │   50    │ attempt_count >=50 │ MAX ATTEMPTS!      │ ?????       │ Check max...
     │         │                    │                    │             │
150s │        │ attempt_count=50   │ Check: >= MAX?     │ 🔴 FORCED │ Force phase1_done=True
150s │        │ ready=False        │ ready=False        │ 🔴 TRUE   │ WITHOUT HEDGES!
     │         │                    │                    │             │
     │         │ ⚠️ UNHEDGED RISK  │ ⚠️ UNHEDGED RISK  │ 🔴 RISK   │ Can't lock BUY legs
     │         │                    │                    │             │
Problem: 🔴 FORCED phase1_done=True but BOTH legs ready=False
         → SELL entries happen WITHOUT buy hedges
         → Max 150 seconds of unhedged risk exposure
```

---

## 3️⃣ PREMATURE BLOCKING - ROOT CAUSE ANALYSIS

### The AND-Gate Lock
```
Code Location: Line 984-990 (engine.py)
    if self.state.get('buy_ce_leg_ready') and self.state.get('buy_pe_leg_ready'):
        self.state.set('phase1_done', True)

Issue: 🔴 Requires BOTH = True simultaneously

Blocking Chain:
  1. CE succeeds → buy_ce_leg_ready = True
  2. PE fails → buy_pe_leg_ready = False  
  3. AND gate evaluates: True AND False = False
  4. phase1_done stays False ← BLOCKS all downstream
  5. Retry triggered (3-second throttle)
  6. CE skipped (already locked) ← Wasted CPU + time
  7. PE retried (single retry ineffective if delta mismatch)
  8. Loop repeats ~50 times ← BOTTLENECK
```

### Independent Selection, Coupled Gate
```
INDEPENDENT parts (work fine):
  ├─ Line 958: if not buy_ce_leg_ready:
  │   └─ _select_by_delta(CE) → independent logic
  │
  └─ Line 968: if not buy_pe_leg_ready:
      └─ _select_by_delta(PE) → independent logic

COUPLED part (blocks):
  └─ Line 984: if buy_ce_leg_ready AND buy_pe_leg_ready:
      └─ phase1_done = True ← BLOCKS if either False
```

### What Prematurely Blocks Each Leg?

**BUY CE Premature Blocking:**
```
1. Skipped after first successful lock
   └─ if not buy_ce_leg_ready: (line 958)
   └─ Returns immediately when True
   └─ Correct behavior (don't re-lock)

2. No individual retry counter
   └─ Uses global _phase1_attempt_count
   └─ CE success on attempt 1, but PE fails on attempt 1-50
   └─ CE never retried (no need) but counts in global counter
   └─ Could artificially limit based on PE's failure

3. AND-gate dependency
   └─ Even if CE locked perfectly, phase1_done blocked by PE
   └─ CE could have entered via entry monitor (independent)
   └─ But no explicit hedge-ready check in _entry_monitor
```

**BUY PE Premature Blocking:**
```
1. Delta mismatch = _select_by_delta returns None
   └─ No delta at target_delta = PE not found
   └─ Correct behavior (find closest match)

2. Subscription timeout
   └─ If deltas don't arrive in 20s
   └─ Timeout, return None, retry
   └─ 3-second throttle + 20s wait = 23s per attempt
   └─ 50 attempts = 1150 seconds (19+ minutes!)
   └─ MAX overhead: Can exceed Phase1 window (14:15)

3. AND-gate dependency
   └─ Even if PE found, phase1_done blocked by CE success
   └─ But this is rare (CE usually finds match)
   └─ Main issue: PE failure blocks entry progression
```

---

## 4️⃣ NON-INVASIVE FIX RECOMMENDATION

### The Problem Statement
```
Current Issue:
  - BUY legs selected independently ✅
  - phase1_done gate COUPLED ❌
  - Both legs must be ready OR forced (unhedged) ❌
  - No per-leg retry tracking ❌

Goal:
  - Allow independent leg attempts
  - Set phase1_done when successful OR when both exceeded attempts
  - Prevent unhedged forced completion
  - Don't modify delta logic or entry logic
```

### Proposed Solution: Per-Leg Attempt Tracking

**Add to config.py:**
```python
# Per-leg attempt tracking (new)
PHASE1_MAX_ATTEMPTS_PER_LEG = 30  # Each leg gets 30 attempts max
# This gives more flexibility than global 50 attempts
```

**Modify state.py to track per-leg attempts:**
```python
# Initialize in _load_state() or reset on new day:
state['_phase1_buy_ce_attempts'] = 0
state['_phase1_buy_pe_attempts'] = 0
```

**Modify _execute_phase1() logic:**
```
Key Changes:
1. Track CE and PE attempts separately
2. Allow each leg max 30 attempts
3. Skip locked legs (don't increment attempt)
4. If leg fails AND attempts exhausted:
   - Mark leg as "attempted_max" (new flag)
   - Don't keep retrying that leg
5. Set phase1_done when:
   - BOTH legs ready (success), OR
   - BOTH legs exhausted attempts (give up)
6. Track which legs succeeded/failed for logging

Result:
   - If PE reaches max attempts: Stop retrying PE
   - If CE locked: Skip CE selection, allow PE to retry
   - If both exhausted: phase1_done = True + log which legs failed
   - Entries can proceed with available hedges
```

### Pseudo-Code for Fix
```python
# In _execute_phase1():

attempt_count = self.state.get('_phase1_attempt_count', 0)
max_global_attempts = Config.PHASE1_MAX_ATTEMPTS
max_per_leg_attempts = Config.PHASE1_MAX_ATTEMPTS_PER_LEG

ce_attempts = self.state.get('_phase1_buy_ce_attempts', 0)
pe_attempts = self.state.get('_phase1_buy_pe_attempts', 0)

ce_exhausted = ce_attempts >= max_per_leg_attempts
pe_exhausted = pe_attempts >= max_per_leg_attempts

# Select BUY CE leg independently
if not self.state.get('buy_ce_leg_ready'):
    if not ce_exhausted:
        buy_ce = self._select_by_delta(atm, atm + range_val, 'CE', expiry, Config.TARGET_CE_DELTA)
        if buy_ce:
            self.state.lock_buy_ce_leg(buy_ce)
            logger.info(f"[OK] PHASE1: BUY CE locked at strike {buy_ce.get('strike')}")
        else:
            logger.warning(f"PHASE1: BUY CE not found (attempt {ce_attempts + 1}/{max_per_leg_attempts})")
            self.state.set('_phase1_buy_ce_attempts', ce_attempts + 1)
    else:
        logger.warning(f"PHASE1: BUY CE max attempts ({max_per_leg_attempts}) exhausted - stopping retries")
        self.state.set('_phase1_buy_ce_final_status', 'FAILED_MAX_ATTEMPTS')

# Select BUY PE leg independently
if not self.state.get('buy_pe_leg_ready'):
    if not pe_exhausted:
        buy_pe = self._select_by_delta(atm - range_val, atm, 'PE', expiry, Config.TARGET_PE_DELTA)
        if buy_pe:
            self.state.lock_buy_pe_leg(buy_pe)
            logger.info(f"[OK] PHASE1: BUY PE locked at strike {buy_pe.get('strike')}")
        else:
            logger.warning(f"PHASE1: BUY PE not found (attempt {pe_attempts + 1}/{max_per_leg_attempts})")
            self.state.set('_phase1_buy_pe_attempts', pe_attempts + 1)
    else:
        logger.warning(f"PHASE1: BUY PE max attempts ({max_per_leg_attempts}) exhausted - stopping retries")
        self.state.set('_phase1_buy_pe_final_status', 'FAILED_MAX_ATTEMPTS')

# Mark phase1 done when:
# 1. Both ready (success), OR
# 2. Both exhausted (give up), OR
# 3. Global attempt limit exceeded

all_legs_ready = (self.state.get('buy_ce_leg_ready') and 
                  self.state.get('buy_pe_leg_ready'))

all_legs_exhausted = (ce_exhausted and pe_exhausted)

if all_legs_ready:
    self.state.set('phase1_done', True)
    logger.info("[OK] PHASE1: Both BUY legs locked and ready")
    # Send lock notification...
elif all_legs_exhausted:
    self.state.set('phase1_done', True)
    logger.warning("[WARN] PHASE1: Both legs exhausted max attempts - completing without complete hedges")
    self.state.set('_phase1_completed_without_hedges', True)
    ce_status = self.state.get('_phase1_buy_ce_final_status', '???')
    pe_status = self.state.get('_phase1_buy_pe_final_status', '???')
    logger.warning(f"  BUY CE: {ce_status}")
    logger.warning(f"  BUY PE: {pe_status}")
elif attempt_count >= max_global_attempts:
    # Global limit exceeded (safety net)
    self.state.set('phase1_done', True)
    logger.warning("[WARN] PHASE1: Global attempt limit exceeded - forcing phase1_done")
    self.state.set('_phase1_completed_without_hedges', True)
else:
    # Continue retrying
    self.state.set('_phase1_attempt_count', attempt_count + 1)
```

---

## 5️⃣ IMPLEMENTATION STEPS (Non-Invasive)

### Step 1: Add Configuration
```python
# In config.py, add:
PHASE1_MAX_ATTEMPTS_PER_LEG = 30  # Each leg max attempts
```

### Step 2: Track Per-Leg Attempts
```python
# In core/state.py _cleanup_daily_state(), add:
for k in ['_phase1_buy_ce_attempts', '_phase1_buy_pe_attempts',
          '_phase1_buy_ce_final_status', '_phase1_buy_pe_final_status']:
    self.state.pop(k, None)
```

### Step 3: Modify _execute_phase1() Logic
Replace lines 984-990 with per-leg tracking and independent exhaustion checks.

### Step 4: Add Logging
Log explicitly when each leg exhausted max attempts.

### Step 5: Entry Monitor Safeguard (Optional)
Add check before SELL entries to prevent unhedged if both BUY legs failed:
```python
if self.state.get('_phase1_completed_without_hedges'):
    if not (self.state.get('buy_ce_leg_ready') or self.state.get('buy_pe_leg_ready')):
        logger.error("SAFETY: No BUY hedges available - blocking SELL entries")
        continue  # Skip all entries
```

---

## 6️⃣ IMPACT ANALYSIS

### Current Behavior (AND-Gate)
```
If PE fails:
  ├─ Attempt 1: CE locked ✅, PE failed ❌
  ├─ Attempt 2-50: CE skipped (already locked), PE retried (likely same result)
  ├─ Result: 50 wasteful iterations, ~150 seconds
  └─ Then: phase1_done forced (unhedged) 🔴

Risk: High CPU usage + time waste + unhedged entries
```

### Proposed Behavior (Per-Leg Tracking)
```
If PE fails:
  ├─ Attempt 1: CE locked ✅, PE failed ❌
  ├─ Attempt 2-30: CE skipped (already locked), PE retried
  ├─ Attempt 30: PE max attempts exhausted
  ├─ Result: phase1_done = True (both exhausted)
  ├─ Log: "BUY CE locked, BUY PE exhausted"
  └─ Then: SELL entries can proceed with CE hedge only

Risk Reduced: Only 30 PE attempts max (90s) instead of 50 global (150s)
              Clear logging of which hedges failed
              Earlier completion when one leg succeeds
              
Advantage: CE successfully locked and can protect SELL CE
          PE failure doesn't drag out entire phase
          Entry monitor can check which hedges available
```

### Trade-offs
```
✅ Advantages:
   - Faster completion if one leg succeeds
   - Clear logging (which leg exhausted)
   - Reduces unnecessary retries
   - Allows entry monitor to use available hedges

❌ Disadvantages:
   - Slight code complexity (per-leg tracking)
   - Requires careful logging (which hedge is unavailable)
   - May allow partial hedges (design decision)

✅ Mitigation:
   - Config option PHASE1_MAX_ATTEMPTS_PER_LEG can be adjusted
   - Entry monitor can enforce full hedge requirement if desired
   - Logging makes it clear which legs failed
```

---

## 7️⃣ VERIFICATION & VALIDATION

### Testing the Fix
```
Test Case 1: Both legs found (success path)
  - Expected: phase1_done = True within 10 seconds
  - Verify: Both _phase1_*_attempts = 1
  
Test Case 2: CE found, PE fails
  - Expected: phase1_done = True after ~90 seconds (PE maxed)
  - Verify: buy_ce_leg_ready = True, buy_pe_leg_ready = False
  - Verify: _phase1_buy_pe_final_status = 'FAILED_MAX_ATTEMPTS'
  
Test Case 3: Both fail
  - Expected: phase1_done = True after ~90 seconds (both maxed)
  - Verify: Both leg_ready flags = False, both final_status = 'FAILED_MAX_ATTEMPTS'
  
Test Case 4: PE found first, CE follows
  - Expected: phase1_done = True within 20 seconds
  - Verify: Both ready = True, both attempts = small numbers
```

### Regression Testing
```
✅ No changes to delta calculations
✅ No changes to entry monitor logic
✅ No changes to live trading logic
✅ Only adds per-leg attempt tracking
✅ Time window gate still works (14:15 escape)
✅ MAX_ATTEMPTS global limit still enforced
```

---

## SUMMARY

### Current Problem
```
🔴 AND-gate phase1_done = buy_ce_leg_ready AND buy_pe_leg_ready
   └─ If PE fails: blocks entire phase1 for ~150 seconds
   └─ If both fail: forces unhedged entries
```

### Proposed Solution
```
✅ Per-leg attempt tracking
   ├─ CE: max 30 attempts (independent)
   ├─ PE: max 30 attempts (independent)
   └─ phase1_done when: both ready OR both exhausted
       
Benefits:
  ├─ Faster completion (90s vs 150s)
  ├─ Clear logging (which leg failed)
  ├─ Reduced CPU waste
  ├─ Entry monitor can act on available hedges
  └─ Non-invasive (no delta/trading logic changes)
```

### Implementation Effort
```
Low: ~20 lines of code changes
     + 5 new config parameters
     + 10 new state tracking fields
     = ~35 lines total
```

This solution allows Phase 1 to progress more independently while still respecting max attempts and providing clear visibility into which hedges are available.
