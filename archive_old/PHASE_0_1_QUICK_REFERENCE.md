# PHASE 0/1 CRITICAL WINDOW - OPERATIONS QUICK REFERENCE

**Status:** ✓ LIVE READY  
**Last Updated:** 2026-02-15

---

## Executive Summary

Automatic failsafe that **prevents missed trades** during NSE market opening (Phase 0/1) when WebSocket disconnects or data goes stale.

---

## OPERATIONS REFERENCE CARD

### Q1: Which flags control Phase 0/1 transitions?
**Answer:** 
- Master: `phase` (STANDBY → PHASE0 → PHASE1 → IN_TRADE → CLOSED)
- Completion: `phase0_done`, `phase1_done`, `_phase1_attempt_count`, `_phase1_completed_without_hedges`
- Per-leg: `*_leg_ready` (sell_ce, sell_pe, buy_ce, buy_pe) - all in `trade_state`
- Entry: `*_entered` flags (same 4 legs)

### Q2: Which functions read these flags?
**Answer:**
- `_phase_monitor()` - Checks `phase0_done`, `phase1_done` every 1-3s
- `_execute_phase0()` - Locks sell legs (phase0_done always succeeds)
- `_execute_phase1()` - Locks buy legs (phase1_done blocked if either buy leg fails)
- `_entry_monitor()` - Checks `*_leg_ready` before entry checks
- `_check_sell_entry()`, `_check_buy_entry()` - Entry condition checks

### Q3: Per-leg actions and _select_by_delta calls?
**Answer:**
- **SELL CE:** Direct find_option() in Phase0, locked immediately
- **SELL PE:** Direct find_option() in Phase0, locked immediately
- **BUY CE:** _select_by_delta() in Phase1 retry loop, locked if found
- **BUY PE:** _select_by_delta() in Phase1 retry loop, locked if found
- Entry checks run when `*_leg_ready` = True

### Q4: Do legs block each other?
**Answer:**
- ✅ SELL ↔ SELL: Independent
- 🔴 BUY ↔ BUY: **GATE** - phase1_done blocked if either BUY leg missing
- ✅ SELL ↔ BUY: Independent
- 🔴 **DEADLOCK POINT:** phase1_done requires BOTH buy legs ready

### Q5: What blocks leg progress?
**Answer:**
1. `_select_by_delta()` returns None (delta mismatch) → ~3s retry throttle
2. Delta data unavailable (ticks not received) → ~20s timeout
3. `phase1_done` stays False → MAX_ATTEMPTS forced ~150s
4. Safety validation fails → 5-30s retry
5. `*_leg_ready` not set → Leg skipped indefinitely
6. MAX_ATTEMPTS exceeded → phase1_done forced (unhedged risk)

### Q6: Runtime trace format?
**Answer:**
```
[PHASE_TRACE] (elapsed_seconds) EVENT: details with flags
[STATE_SNAPSHOT] elapsed_seconds
  Phase: PHASE1
  Phase 0: done=True
  Phase 1: done=False attempts=3 without_hedges=False
  SELL CE: ready=True entered=False
  ...all 4 legs...
```

---

## 🎯 THE DEADLOCK IN ONE PICTURE

```
Phase 1 window (09:25-14:15)

Loop every 3 seconds:
  1. Try select BUY CE by delta
     ├─ If found: lock, buy_ce_leg_ready=True
     └─ If not found: continue (skip locks)
  
  2. Try select BUY PE by delta
     ├─ If found: lock, buy_pe_leg_ready=True
     └─ If not found: continue (skip locks)
  
  3. Check GATE:
     if buy_ce_leg_ready AND buy_pe_leg_ready:
       phase1_done = True ✅ MOVE TO TRADING
     elif attempts >= 50:
       phase1_done = True (forced) 🔴 NO HEDGES
     else:
       retry again (wait 3 seconds)

RISK: If BUY PE stuck on "delta mismatch" → 50+ attempts → 150+ seconds
      Then phase1_done forced WITHOUT buy_pe_leg → Unhedged entries

SAFEGUARD: Time window gate auto-moves phase at 14:15 IST
```

---

## 📁 DOCUMENTATION FILES CREATED

### Core Diagnostic Files
1. **[PHASE_0_1_DIAGNOSIS_INDEX.md](PHASE_0_1_DIAGNOSIS_INDEX.md)** ← START HERE
   - Master index with navigation
   - Executive summary
   - Configuration tuning guide
   - Escalation procedures

2. **[PHASE_0_1_TRACE_SUMMARY.md](PHASE_0_1_TRACE_SUMMARY.md)** ← QUICK ANSWERS
   - All 6 questions answered
   - Critical findings
   - Recommendations
   - 5-10 min read

3. **[PHASE_0_1_DEADLOCK_DIAGNOSIS.md](PHASE_0_1_DEADLOCK_DIAGNOSIS.md)** ← DETAILED ANALYSIS
   - Code-level traces with line numbers
   - Scenario analysis (4 deadlock scenarios)
   - Flag dependencies
   - 20-30 min read

4. **[PHASE_0_1_DEADLOCK_VISUAL_MAP.md](PHASE_0_1_DEADLOCK_VISUAL_MAP.md)** ← FLOW DIAGRAMS
   - State flow ASCII diagram
   - Flag dependency tree
   - Blocking chain sequences
   - Quick reference checklist
   - Config parameters

### Testing & Debugging Files
5. **[PHASE_0_1_DEBUG_CHECKLIST.md](PHASE_0_1_DEBUG_CHECKLIST.md)** ← HOW TO TEST & DEBUG
   - Pre-deployment review (7 checks)
   - Live test procedures (5 tests)
   - Debugging guides
   - Emergency diagnostics
   - Recovery steps
   - Success metrics

6. **[PHASE_0_1_TRACE.py](PHASE_0_1_TRACE.py)** ← DIAGNOSTIC SCRIPT
   - Python script that instruments engine
   - Logs all phase/leg transitions
   - Runtime snapshots with timestamps
   - Usage: `python PHASE_0_1_TRACE.py`

---

## 🚀 HOW TO USE (By Scenario)

### Scenario 1: "I want to understand Phase 0/1"
→ Read: [PHASE_0_1_TRACE_SUMMARY.md](PHASE_0_1_TRACE_SUMMARY.md) (10 min)
→ Then: [PHASE_0_1_DEADLOCK_VISUAL_MAP.md](PHASE_0_1_DEADLOCK_VISUAL_MAP.md) (15 min)

### Scenario 2: "Phase is stalling, I need to debug"
→ First: Check the current state and logs
→ Then: Follow [PHASE_0_1_DEBUG_CHECKLIST.md](PHASE_0_1_DEBUG_CHECKLIST.md)
→ Deep dive: [PHASE_0_1_DEADLOCK_DIAGNOSIS.md](PHASE_0_1_DEADLOCK_DIAGNOSIS.md)

### Scenario 3: "I need to verify everything works"
→ Use: [PHASE_0_1_DEBUG_CHECKLIST.md](PHASE_0_1_DEBUG_CHECKLIST.md) pre-deployment checks
→ Run: Live tests T1-T5
→ Monitor: Success metrics

### Scenario 4: "System shows phase1_done forced, what happened?"
→ Check: [PHASE_0_1_DEADLOCK_VISUAL_MAP.md](PHASE_0_1_DEADLOCK_VISUAL_MAP.md) "Scenario: Max Attempts Reached"
→ Look at: `_phase1_completed_without_hedges=true`
→ Action: Follow recovery steps in checklist

### Scenario 5: "I need to troubleshoot a specific failure"
→ Logs → Identify symptom
→ Reference: [PHASE_0_1_DEBUG_CHECKLIST.md](PHASE_0_1_DEBUG_CHECKLIST.md) "DEBUGGING CHECKLIST"
→ Detailed analysis: [PHASE_0_1_DEADLOCK_DIAGNOSIS.md](PHASE_0_1_DEADLOCK_DIAGNOSIS.md)

---

## 🔍 KEY FINDINGS

### The Deadlock Mechanism
```
┌──────────────────────────────────────────────┐
│ Phase 1 requires: BUY_CE_READY AND BUY_PE_READY
│ If BUY_PE_DELTA_MISMATCH:
│   └─ Retries every 3 seconds
│      └─ Up to 50 attempts (150 seconds)
│         └─ Then forced (no hedges)
└──────────────────────────────────────────────┘
```

### Why It Happens
1. Market deltas don't match `CONFIG.TARGET_*_DELTA`
2. Strike range too narrow (`DELTA_SCAN_RANGE` too small)
3. Time window insufficient for delta data
4. Underlying moving faster than selection

### Current Safeguards
✅ MAX_ATTEMPTS prevents infinite loop  
✅ Time gate auto-transitions phase  
✅ phase1_done forced at max (allows progression)  
✅ Independent entry checks work without phase1_done

### Remaining Risk
🔴 **Unhedged entries** if phase1 forced without buy legs

### Can Be Fixed By
- Broadening DELTA_SCAN_RANGE
- Relaxing TARGET_*_DELTA values
- Increasing PHASE1_MAX_ATTEMPTS or wait time
- Adding hedge requirement check before SELL entries

---

## ✅ VERIFICATION CHECKLIST (Before Going Live)

- [ ] Read all 6 answers above
- [ ] Understand the deadlock mechanism (flag gate)
- [ ] Review configuration parameters (DELTA_SCAN_RANGE, etc.)
- [ ] Know the success metrics (Phase 0 < 5 min, Phase 1 < 15 min)
- [ ] Can identify unhedged condition (phase1_completed_without_hedges)
- [ ] Know how to extract state from logs
- [ ] Have runbook for recovery (in checklist)
- [ ] Can run diagnostic script if needed

---

## 📞 QUICK DECISION TREE

```
Issue: Phase seems stuck?
│
├─ Check: Is time < PHASE0_END (09:25)?
│  └─ YES: Phase 0 still running, normal
│  └─ NO: Continue
│
├─ Check: Is time < PHASE1_END (14:15)?
│  └─ YES: Phase 1 running, check metrics (below)
│  └─ NO: Phase 1 done, check entries
│
├─ Check (if Phase 1): _phase1_attempt_count value?
│  ├─ < 10: Normal retrying, let it continue
│  ├─ 10-35: Struggling, watch deltas in logs
│  ├─ 35-45: Critical, investigate blocking leg
│  └─ >= 50: Already forced, check unhedged entries
│
├─ Check: which leg is stuck?
│  ├─ BUY_CE: Check CE delta values in logs
│  └─ BUY_PE: Check PE delta values in logs
│
└─ Action: Read PHASE_0_1_DEBUG_CHECKLIST.md
```

---

## ⚙️ CONFIGURATION QUICK TUNE

**If Phase 1 keeps hitting max attempts:**
```python
# Make search more lenient
Config.DELTA_SCAN_RANGE = 3  # Was: 2
Config.TARGET_CE_DELTA = 0.30  # Accept deltas 0.25-0.35
Config.TARGET_PE_DELTA = -0.30  # Accept deltas -0.25 to -0.35
Config.PHASE1_MAX_ATTEMPTS = 100  # Was: 50
```

**If deltas not arriving in time:**
```python
Config.PHASE1_DATA_WAIT_SECONDS = 30  # Was: 20
Config.PHASE1_DATA_CHECK_INTERVAL = 0.5  # Check more frequently
```

**To prevent unhedged entries:**
```python
# Add to _entry_monitor() before SELL checks:
if not (self.state.get('buy_ce_leg_ready') or self.state.get('buy_pe_leg_ready')):
    logger.error("No BUY hedges ready - blocking SELL entries")
    continue  # Skip SELL entry checks
```

---

## 📊 HEALTH INDICATORS (Monitor Daily)

```
Time Window       Expected State                    Action if !=
─────────────────────────────────────────────────────────────────
09:15-09:25       phase0 running                   Check Phase0 logs
09:25-09:35       phase0_done=True                 Debug Phase0
09:25-14:15       phase1 running                   Monitor Phase1
09:35-14:00       phase1_done=True                 Check Phase1 config
                  buy_ce_leg_ready=True
                  buy_pe_leg_ready=True
14:15+            All entries completed           Review day's trades
                  No unhedged positions
```

---

## 🎓 LEARNING HIERARCHY

**Level 0 (Absolute Beginner):**
- Read this card
- This is all you need to understand the issue

**Level 1 (Operator):**
- Read PHASE_0_1_TRACE_SUMMARY.md
- Learn to identify symptoms
- Know when to escalate

**Level 2 (Developer):**
- Read all core files
- Understand root causes
- Can tune configuration

**Level 3 (Architect):**
- Read all files + original code
- Can design fixes
- Can hardening features

---

## 📝 FINAL NOTES

**Diagnosis is COMPLETE.** All 6 questions answered.  
**No code changes needed** for monitoring and debugging.  
**Ready for production** with surveillance.  

**Permanent improvements** (if desired):
1. Broader delta search range
2. Dynamic delta targets (market-aware)
3. Fallback delta targets
4. Mandatory hedge requirement

**For now:** Deploy with monitoring, collect metrics, tune if needed.

---

**Generated:** 15 Feb 2026  
**Status:** ✅ READY  
**Next Action:** Review summary file, then deploy monitoring
