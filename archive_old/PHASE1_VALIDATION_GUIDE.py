#!/usr/bin/env python3
"""
PHASE 1 VALIDATION AND DEPLOYMENT GUIDE
========================================

Quick reference for validating Phase 1 implementation and deploying to production.
Follow these steps in order.

Created: February 14, 2026
System: trading_system_fixed
"""

print("""

           PHASE 1 VALIDATION AND DEPLOYMENT GUIDE                              


QUICK CHECKLIST


Before Starting:
 All files modified and pushed to git
 Run test_phase1_fixes.py to verify core functionality
 Check git status - no uncommitted changes


STEP 1: Validate Test Suite


Command:
  python test_phase1_fixes.py -v

Expected Output:
   TestPhaseConstants (all phase constants)
   TestStateNormalization (legacy format conversion)
   TestDeltaBounds (time/attempt guards)
   TestProtocolConformance (missing method detection)
   TestPhaseTransitions (validation logic)
   TestExecutionGateway (singleton, rate limiting)
   TestStateLocksAndProtocol (lock returns bool)

If ANY test fails:  DO NOT PROCEED
Fix the failing test and re-run.


STEP 2: Validate REPLAY Mode Daily Test


Command:
  export DATA_MODE=REPLAY
  export TRADING_MODE=PAPER
  export REPLAY_START_DATE=2026-02-04
  export REPLAY_END_DATE=2026-02-04
  export DEBUG_MODE=true
  python main.py

Expected Behavior:
  [09:15] STANDBY  initializes
  [09:16] PHASE_PHASE0  selects spot reference
  [09:16] PHASE_PHASE1  selects option strikes
  [14:15+] PHASE_IN_TRADE  enters trades
  [15:25] PHASE_CLOSED  stops trading

Expected Logs:
   NOTIFIER_OK message (if notifier configured)
   Phase transitions using constants (PHASE_STANDBY, PHASE_IN_TRADE, etc.)
   Phase monitoring running
   Entry and exit monitoring
   No errors in delta calculation
   State file contains 'legs' object

Critical Messages to Find:
  - " Sufficient data received" (successful Phase 1)
  - DELTA SELECTED (or DELTA_SCAN_FAILED with explanation)
  - "[SELL_ENTRY_CHECK] CONDITION MET" (entry triggered)
  - Trade orders logged

If NO Trades Executed:
  - Check REPLAY_DATA_DIR has tick data
  - Check Phase 1 didn't fail (search logs for "DELTA_SCAN_FAILED")
  - Verify strike selection logged correctly
  - Check entry conditions met (decay %, trigger levels)

If Errors Found:  DO NOT PROCEED
Debug the error, fix, and re-test REPLAY mode.


STEP 3: Validate State Normalization


Check Generated State File:
  cat strategy_state.json | python -m json.tool

Expected Structure:
  {
    "legs": {
      "sell_ce": {"entered": bool, "token": str, "sl": float, "qty": -int},
      "sell_pe": {...},
      "buy_ce": {...},
      "buy_pe": {...}
    },
    "phase": "IN TRADE",  (or other valid phase)
    "phase1_done": true
  }

Validation:
   'legs' object exists
   All 4 leg types present (sell_ce, sell_pe, buy_ce, buy_pe)
   Each leg has: entered, token, sl, qty
   'phase' is one of: STANDBY, PHASE0, PHASE1, INIT, IN TRADE, CLOSED
   qty is negative for sell legs, positive for buy legs


STEP 4: Verify Protocol Assertions


Search logs for protocol validation:
  grep "NOTIFIER PROTOCOL ASSERTION" *.log

Expected:
   NOTIFIER PROTOCOL ASSERTION PASSED - all X required methods verified

If you see ERROR instead:
   Notifier missing required methods
  DO NOT deploy - fix notifier implementation first


STEP 5: Test Kill-Switch and Rate Limiting


Test Kill-Switch:
  export KILL_SWITCH_ENABLED=true
  python main.py &
  sleep 2
  # Try to place an order - should be blocked

Expected:
   KILL SWITCH ACTIVE - All trading halted
  Order status: REJECTED

Test Rate Limiting:
  export MAX_ORDERS_PER_MINUTE=2
  python main.py

Expected (after 2 orders):
  Rate limit: 2/2 orders/min
  3rd order blocked

If either test fails:  DO NOT PROCEED
Check execution gateway integration in brokers.


STEP 6: Verify Phase Transitions Log Correctly


Run REPLAY mode again and check logs:
  python main.py 2>&1 | grep "PHASE TRANSITION"

Expected Output:
   PHASE TRANSITION: INIT  STANDBY
   PHASE TRANSITION: STANDBY  PHASE0
   PHASE TRANSITION: PHASE0  PHASE1
   PHASE TRANSITION: PHASE1  IN TRADE
   PHASE TRANSITION: IN TRADE  CLOSED

All transitions should use constants (not raw strings).


STEP 7: Cross-Check All Files Are Modified


Files Modified (should exist and have changes):
   contract.py - Check lines 142-172 (protocol docstrings)
   diagnose_no_trades.py - Check lines 26-36 (legacy format detection)
   check_entry_readiness.py - Check lines 1-25 (constants import)
   utils/delta_utils.py - Check lines 323-363 (scan_strikes_with_bounds)
   strategy/engine.py - Check lines 170-277 (set_phase, _modify_sl_with_retry)
   core/state.py - Check lines 27-63 (_normalize_legacy_state)
   utils/notifier.py - Check lines 42-93 (protocol assertion)

Files Created:
   test_phase1_fixes.py - Should exist

Execute Check:
  git diff --stat | grep -E "(contract|diagnose|check_entry|delta_utils|engine|state|notifier|test_phase1)"

Should show modifications to 8 files.


PERFORMANCE VALIDATION


Verify No Performance Degradation:
  
Before Phase 1:
  time python main.py  # Note: runtime for 1 full day REPLAY

After Phase 1:
  time python main.py  # Should be similar

Expected:
  - No change in overall runtime
  - All operations complete within time windows
  - Memory usage similar
  - No memory leaks (check after 1 hour)


DEPLOYMENT PHASES


IF ALL TESTS PASS 

Deploy to Staging:
  1. Backup current production config
  2. Deploy Phase 1 code to staging
  3. Run full day REPLAY test
  4. Run manual smoke test with TRADING_MODE=PAPER
  5. Get sign-off from risk team

Deploy to Production:
  1. Schedule during non-market hours
  2. Deploy code
  3. Monitor first 2 trades carefully
  4. Check each phase transition in logs
  5. Monitor notifier messages
  6. Watch for any protocol errors
  7. After 1 full trading day, confirm success


ROLLBACK PLAN (if needed)


If critical issues found:
  1. git revert [commit-hash]
  2. git push production
  3. Restart trading system
  4. Systems will auto-downgrade to previous state format

Note: Structured state will remain, but system will work with both formats.


AFTER DEPLOYMENT VALIDATION


First 24 Hours:
   Phase transitions log correctly (all constants)
   No errors in protocol assertions
   State file contains structured 'legs' object
   All trades execute normally
   Notifier sends messages without errors
   No sign of infinite loops or deadlocks

First 1 Week:
   Multiple trading days complete successfully
   State normalization works for legacy files
   Kill-switch tested and verified blocking orders
   Trailing SL updates correctly
   Delta scan completes within time limits
   No performance degradation

Production Ready Checklist:
   All tests pass
   REPLAY mode test succeeds
   Protocol assertions pass
   Phase transitions log correctly
   State normalization works
   Kill-switch functional
   Rate limiting enforced
   No regressions detected
   Performance unchanged


SUPPORT AND TROUBLESHOOTING


Common Issues and Solutions:

Issue: " NOTIFIER PROTOCOL ASSERTION FAILED"
Solution: Ensure notifier has all 9 required methods (see contract.py)

Issue: "DELTA_SCAN_FAILED" in Phase 1
Solution: Increase PHASE1_DATA_WAIT_SECONDS in config or .env

Issue: " INVALID PHASE"
Solution: Ensure all phase assignments use constants (not raw strings)

Issue: "Rate limit: X/Y orders/min" blocks valid orders
Solution: Increase MAX_ORDERS_PER_MINUTE in config

Issue: State file corrupted
Solution: Delete strategy_state.json to reset, will be recreated with new structure

Issue: Legacy state not converting
Solution: Check core/state.py _normalize_legacy_state() is called in __init__

Issue: SL modification fails repeatedly
Solution: Check broker supports modify_order(), verify order_id is correct


PERFORMANCE MONITORING


Monitor these metrics after deployment:

CPU Usage:
  Expected: Similar to before
  If higher: Check for busy-waiting loops
  
Memory Usage:
  Expected: Stable throughout day
  If increasing: Check for memory leaks in state storage
  
Disk I/O:
  Expected: Occasional writes to strategy_state.json
  If frequent: May indicate excessive state updates
  
Order Latency:
  Expected: No change from before
  If increased: Check execution gateway not adding delay


SIGN-OFF CHECKLIST


   [ ] All unit tests pass
   [ ] REPLAY mode test succeeds
   [ ] Code review completed
   [ ] Risk team approval obtained
   [ ] Staging test completed
   [ ] Rollback plan documented
   [ ] Deployment time scheduled
   [ ] Team notified
   [ ] Monitoring enabled
   [ ] First trade manually verified
   [ ] Protocol assertion logged
   [ ] State file structure correct
   [ ] Performance unchanged
   [ ] 24-hour monitoring completed
   [ ] Week-long validation completed
   [ ] Phase 1 deployment APPROVED


For questions or issues, refer to:
  - PHASE1_IMPLEMENTATION_COMPLETE.md (detailed changes)
  - test_phase1_fixes.py (test implementations)
  - contract.py (protocol definitions)
  - strategy/engine.py (phase management logic)


""")

print(" Validation guide ready. Follow steps in order for successful deployment.")
print("\nNext Step: Run: python test_phase1_fixes.py -v")
