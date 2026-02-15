# STRATEGY LOGIC – DETAILED FLOW DIAGRAMS & PER-LEG ANALYSIS

**Status:** ✅ Supplementary Documentation (Diagrams, Tables, Examples)  
**Purpose:** Visual flow maps and detailed per-leg decision matrices

---

## FLOW DIAGRAM 1: System Initialization & Thread Startup

```
┌─────────────────────────────────────────────────────────────────┐
│ main.py ENTRY POINT                                             │
│ create_broker() → create_state() → create_instruments()         │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ Initialize StrategyEngine│
        │ (Feed, Broker, State)  │
        │ ✓ ValidateNotifier      │
        │ ✓ InitPhaseManager      │
        │ ✓ InitSafetyValidator   │
        └──────────┬─────────────┘
                   │
                   ▼
        ┌─────────────────────────────────┐
        │ engine.start()                  │
        │ ├─ Check broker positions       │
        │ ├─ Enter STANDBY mode           │
        │ ├─ Resubscribe on restart       │
        │ └─ Launch 6 daemon threads:     │
        └──┬──────────────────────────────┘
           │
    ┌──────┴──────────────────────────────────────────────┐
    │                                                      │
    ▼                                                      ▼
┌─────────────────────────────┐          ┌────────────────────────┐
│ THREAD 1: _phase_monitor    │          │ Feed (SmartConnect)    │
│ Interval: 0.5-1s            │          │ ↓ Async Ticks          │
│ Checks: IST time window     │          │ _on_tick() callback    │
│ Updates: phase, phase*_done │          │ Updates: snapshots     │
│ Calls: _execute_phase0/1()  │          └────────────────────────┘
└─────────────────────────────┘
    ▼
┌─────────────────────────────┐          ┌────────────────────────┐
│ THREAD 2: _entry_monitor    │          │ THREAD 3: _exit_monitor│
│ Interval: Loop enforced     │          │ Interval: Loop enforced│
│ Gate: Broker reconcile      │          │ Gate: Phase==IN_TRADE  │
│ Checks: Decay/Appreciation  │          │ Checks: SL/TP/Trailing │
│ Updates: *_entered flags    │          │ Updates: *_exited      │
└─────────────────────────────┘          └────────────────────────┘
    ▼                                          ▼
┌──────────────────────────┐          ┌────────────────────────┐
│ THREAD 4: Squareoff      │          │ THREAD 5: Heartbeat    │
│ Gate: time >= 14:30      │          │ Interval: ~30s         │
│ Action: Force close all  │          │ Action: Send snapshots │
│ Updates: *_exited = True │          │ Notifier callback      │
└──────────────────────────┘          └────────────────────────┘
    ▼
┌──────────────────────────────────┐
│ THREAD 6: Trailing Observation   │
│ Window: 12:00-14:15              │
│ Phase 1: Observe (12:00-14:00)   │
│ Phase 2: Freeze (14:00)          │
│ Phase 3: Neutral gap (14:00-15)  │
│ Phase 4: Activate (14:15+)       │
│ Tracks: Adverse prices only      │
└──────────────────────────────────┘
```

---

## FLOW DIAGRAM 2: Phase 0 (SELL Leg Selection)

```
IST Time: 09:25 - 11:00

┌──────────────────────────────────────────────────┐
│ _phase_monitor() detects PHASE0 window           │
│ phase != PHASE_PHASE0 → set_phase(PHASE0)        │
└─────────────────┬────────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────────┐
        │ _execute_phase0()       │
        │ Called every 1 second   │
        │ (throttle)              │
        └────────┬────────────────┘
                 │
        ┌────────┴────────────────────────────┐
        │                                      │
        ▼                                      ▼
   ┌─────────────────┐          ┌────────────────────────┐
   │ Get SPOT price  │          │ Subscribe to SPOT      │
   │ find_spot()     │          │ feed.subscribe()       │
   │ feed.get_ltp()  │          │ Track subscription     │
   └────────┬────────┘          └────────────────────────┘
            │
            ▼
   ┌─────────────────────────────┐
   │ Calculate ATM               │
   │ atm = (spot_ltp / 100) * 100│
   │ Example: spot=23950 → atm=23900
   └────────────┬────────────────┘
                │
        ┌───────┴───────────────┐
        │                       │
        ▼                       ▼
   ┌──────────────────┐  ┌──────────────────┐
   │ SELL CE Strike   │  │ SELL PE Strike   │
   │ atm - offset     │  │ atm + offset     │
   │ 23900 - 100 = 23800 │ 23900 + 100 = 24000
   └────────┬─────────┘  └────────┬─────────┘
            │                     │
            ▼                     ▼
   ┌─────────────────────────────────────────┐
   │ find_option(strike, 'CE'/'PE', expiry) │
   │ Search InstrumentMaster                │
   │ Return: token, symbol, strike          │
   └──┬──────────────────────────────┬──────┘
      │                              │
      ▼                              ▼
 ┌─────────────────────┐  ┌───────────────────────┐
 │ Subscribe CE token  │  │ Subscribe PE token    │
 │ feed.subscribe()    │  │ feed.subscribe()      │
 └────────┬────────────┘  └────────┬──────────────┘
          │                        │
          ▼                        ▼
 ┌──────────────────────────────────────────┐
 │ Wait for option prices (1s + 1s)         │
 │ feed.get_ltp(sell_ce_token)              │
 │ feed.get_ltp(sell_pe_token)              │
 │ Store as: sell_ce_ref_premium, sell_pe_ref_premium
 └────────┬─────────────────────────────────┘
          │
          ▼
 ┌─────────────────────────────────────┐
 │ Lock SELL CE leg                    │
 │ state.lock_sell_ce_leg({            │
 │   'token': token,                   │
 │   'strike': strike,                 │
 │   'symbol': symbol,                 │
 │   'ltp': ltp                        │
 │ })                                  │
 │ Sets: sell_ce_leg_ready = True      │
 └────────┬─────────────────────────────┘
          │
          ▼
 ┌─────────────────────────────────────┐
 │ Lock SELL PE leg (Same as CE)       │
 │ Sets: sell_pe_leg_ready = True      │
 └────────┬─────────────────────────────┘
          │
          ▼
 ┌─────────────────────────────────────┐
 │ Set phase0_done = True              │
 │ Return (phase0 complete)            │
 │ Next iteration: throttle 0.5s       │
 │ (No more Phase 0 calls)             │
 └─────────────────────────────────────┘
```

---

## FLOW DIAGRAM 3: Phase 1 (BUY Leg Selection)

```
IST Time: 11:00 - 14:15

┌──────────────────────────────────────────────────┐
│ _phase_monitor() detects PHASE1 window           │
│ phase != PHASE_PHASE1 → set_phase(PHASE1)        │
└─────────────────┬────────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────────┐
        │ _execute_phase1()       │
        │ Called every 3 seconds  │
        │ (throttle)              │
        │ Per-leg retry logic     │
        └────────┬────────────────┘
                 │
    ┌────────────┴──────────────────────┐
    │                                   │
    ▼                                   ▼
┌──────────────────────┐          ┌──────────────────────┐
│ Check both BUY legs  │          │ Check attempt count  │
│ ready already?       │          │ _phase1_attempt_count│
│ If yes: Done         │          │ >= 3? Force done     │
│ Skip rest of phase   │          │ (safety net)         │
└───────┬──────────────┘          └──────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│ Get ATM (from PHASE0 store)    │
│ OR calculate independently      │
│ If no Phase0: calculate         │
│   spot_ltp → ATM                │
└────────┬────────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│ Get Expiry from state            │
│ OR fetch nearest expiry          │
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│ Define Range = DELTA_SCAN_RANGE * 100   │
│ Typically: 5 * 100 = 500 strike range   │
│ BUY CE: [ATM, ATM+500]                   │
│ BUY PE: [ATM-500, ATM]                   │
└────────┬─────────────────────────────────┘
         │
    ┌────┴────────────────────────┐
    │                             │
    ▼                             ▼
┌─────────────────────┐    ┌──────────────────┐
│ Check buy_ce_ready? │    │ Check buy_pe_ready
│ No → find CE options│    │ No → find PE options
│ Yes → skip          │    │ Yes → skip
└────────┬────────────┘    └────────┬─────────┘
         │                          │
         ▼                          ▼
┌─────────────────────────────────────────┐
│ find_options_in_range()                │
│ Returns list of matching options        │
│ With: token, symbol, strike             │
└────────────┬────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ Subscribe all options to feed        │
│ feed.subscribe(tokens_list)          │
│ Track subscription time              │
└────────┬─────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│ Wait for data (20s max)            │
│ Check delta availability           │
│ Proceed when 50% ready             │
│                                    │
│ If timeout: return (retry next 3s) │
└────────┬───────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│ PER-LEG BUY CE SELECTION                  │
│ (Independent from BUY PE)                 │
│                                           │
│ ce_attempts = state.get('_phase1_buy_ce_attempts', 0) │
│ max_per_leg = 30                         │
│ ce_exhausted = (ce_attempts >= 30)       │
│                                           │
│ IF NOT buy_ce_leg_ready:                 │
│    IF NOT ce_exhausted:                  │
│        buy_ce = _select_by_delta()       │
│        IF buy_ce found:                  │
│           state.lock_buy_ce_leg(buy_ce)  │
│           buy_ce_leg_ready = True        │
│        ELSE:                             │
│           ce_attempts += 1               │
│           sleep(3)                       │
│           return (retry next cycle)      │
│    ELSE:                                 │
│        Mark: _phase1_buy_ce_final_status │
│        = "FAILED_MAX_ATTEMPTS"           │
└────────┬─────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│ PER-LEG BUY PE SELECTION                  │
│ (IDENTICAL to CE, completely independent) │
│                                           │
│ pe_attempts = state.get('_phase1_buy_pe_attempts', 0) │
│ pe_exhausted = (pe_attempts >= 30)       │
│                                           │
│ [Same logic as CE]                        │
└────────┬─────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│ GATE DECISION (3 Conditions)           │
│                                        │
│ IF both_ready:                         │
│    phase1_done = True [SUCCESS] ✅    │
│                                        │
│ ELIF both_exhausted:                   │
│    phase1_done = True                  │
│    Log: "Both exhausted, proceeding    
│           with available hedges"       │
│                                        │
│ ELIF attempt_count >= max_attempts:   │
│    phase1_done = True [SAFETY NET]    │
│                                        │
│ ELSE:                                  │
│    Continue (will retry in 3s)        │
└────────────────────────────────────────┘
```

---

## FLOW DIAGRAM 4: Entry Monitor (Parallel Independent Legs)

```
IST Time: 14:15+ (PHASE_IN_TRADE)

┌────────────────────────────────────────────┐
│ _entry_monitor() [Continuous Loop]         │
│ Checks each leg independently              │
│ Interval: Loop enforced dynamically        │
└─────────┬──────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────┐
│ SAFETY BLOCK 1: Broker Reconciliation  │
│ Call: safety_validator.validate_()     │
│ On mismatch: sleep(5), continue        │
└─────────┬──────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────┐
│ SAFETY BLOCK 2: Leg Independence       │
│ Call: safety_validator.verify_leg_()   │
│ On violation: sleep(5), continue       │
└─────────┬──────────────────────────────┘
          │
    ┌─────┴─────┬─────────┬────────┐
    │           │         │        │
    ▼           ▼         ▼        ▼
┌───────┐  ┌───────┐  ┌───────┐ ┌───────┐
│SELL CE│  │SELL PE│  │BUY CE │ │BUY PE │
│CHECK  │  │CHECK  │  │CHECK  │ │CHECK  │
└───┬───┘  └───┬───┘  └───┬───┘ └───┬───┘
    │          │          │         │
    ▼          ▼          ▼         ▼
    
SELL CE Entry Check:
├─ sell_ce_leg_ready? Yes → continue
└─ sell_ce_entered? No → continue
   └─ Get token, ref_premium from state
      ├─ token = 123456
      ├─ ref_premium = 50.00 (Phase 0 price)
      └─ Get current LTP = 46.80
         ├─ decay = 50.00 - 46.80 = 3.20
         ├─ trigger = 3.00 (Config.SELL_DECAY_TRIGGER)
         └─ 3.20 >= 3.00? YES → Place order
            ├─ Order: SELL 25 contracts @ 46.80
            ├─ Status: FILLED
            └─ state.sell_ce_entered = True
               state.sell_ce_entry_price = 46.80
            
            [SAME FOR SELL PE, BUY CE, BUY PE]
            [Each leg completely independent]
    │
    └─────────────────────────────────────┐
                                         │
                                         ▼
                            ┌──────────────────────┐
                            │ Enforce loop interval│
                            │ _enforce_interval()  │
                            └─────────┬────────────┘
                                      │
                                      ▼
                            ┌──────────────────────┐
                            │ Loop back to start   │
                            │ (Continuous)         │
                            └──────────────────────┘
```

---

## FLOW DIAGRAM 5: Exit Monitor (Parallel Independent Legs)

```
IST Time: PHASE_IN_TRADE (14:15 - 14:30)

┌──────────────────────────────────────┐
│ _exit_monitor() [Continuous Loop]    │
│ Only runs when phase == PHASE_IN_TRADE
└───────┬──────────────────────────────┘
        │
        ▼
    ┌───────────┬──────────────┬──────────────┐
    │           │              │              │
    ▼           ▼              ▼              ▼
┌────────────────────────────────────────────────────┐
│ SELL CE Exit Check                                │
│                                                  │
│ IF entered AND NOT exited:                      │
│    Get LTP = 46.90 (current price)              │
│    Entry = 46.80                                │
│                                                  │
│    ┌─ Fixed SL/TP (always calculated) ─┐       │
│    │ fixed_sl = 46.80 * 1.05 = 49.14   │       │
│    │ tp = 46.80 * 0.99 = 46.33         │       │
│    └────────────────────────────────────┘       │
│                                                  │
│    ┌─ Trailing SL (14:15+, if applies) ────┐   │
│    │ IF 14:15 <= now < 14:30:               │   │
│    │    read stored _adverse_price = 48.50 │   │
│    │    trailing_sl = 48.50 * 1.02 = 49.47│   │
│    │    IF 49.47 < 49.14:                  │   │
│    │        use trailing_sl                │   │
│    │    ELSE:                              │   │
│    │        use fixed_sl                   │   │
│    └────────────────────────────────────────┘   │
│                                                  │
│    Final SL = 49.14 (or 49.47 if tighter)      │
│                                                  │
│    Compare:                                      │
│    IF ltp >= sl (46.90 < 49.14):               │
│        NO EXIT YET                              │
│    ELIF ltp <= tp (46.90 > 46.33):             │
│        NO EXIT YET                              │
│    else continue next iteration                  │
└────────────────────────────────────────────────────┘
    │
    └─────────────────────────────────────────┐
                                              │
                                              ▼
                                ┌──────────────────────┐
                                │ [SAME FOR SELL PE]   │
                                │ [SAME FOR BUY CE/PE] │
                                │                      │
                                │ BUY CE/PE use fixed  │
                                │ SL only (no trailing)
                                └──────┬───────────────┘
                                       │
                                       ▼
                                ┌──────────────────────┐
                                │ Enforce loop interval│
                                │ Loop back           │
                                └──────────────────────┘
```

---

## PER-LEG DECISION MATRIX 1: SELL Entry

| Leg | Ready Flag | Entered Flag | Condition | Action | Update |
|-----|-----------|-------------|-----------|--------|--------|
| SELL CE | ✅ True | ❌ False | decay >= 3.0 | Place SELL order | entered=True, entry_price=X |
| SELL CE | ✅ True | ❌ False | decay < 3.0 | Skip (wait for decay) | None |
| SELL CE | ✅ True | ✅ True | — | Skip (already traded) | None |
| SELL PE | ✅ True | ❌ False | decay >= 3.0 | Place SELL order | entered=True, entry_price=X |
| SELL PE | ✅ True | ❌ False | decay < 3.0 | Skip (wait for decay) | None |
| SELL PE | ✅ True | ✅ True | — | Skip (already traded) | None |

---

## PER-LEG DECISION MATRIX 2: BUY Entry

| Leg | Ready Flag | Entered Flag | Condition | Action | Update |
|-----|-----------|-------------|-----------|--------|--------|
| BUY CE | ✅ True | ❌ False | ltp >= trigger | Place BUY order | entered=True, entry_price=X |
| BUY CE | ✅ True | ❌ False | ltp < trigger | Skip (wait for rise) | None |
| BUY CE | ✅ True | ✅ True | — | Skip (already traded) | None |
| BUY PE | ✅ True | ❌ False | ltp >= trigger | Place BUY order | entered=True, entry_price=X |
| BUY PE | ✅ True | ❌ False | ltp < trigger | Skip (wait for rise) | None |
| BUY PE | ✅ True | ✅ True | — | Skip (already traded) | None |

---

## PER-LEG DECISION MATRIX 3: SELL Exit

| Leg | Entered? | Exited? | LTP | SL | TP | Action | Reason |
|-----|----------|---------|-----|----|----|--------|--------|
| SELL CE | ✅ | ❌ | 49.14 | 49.14 | 46.33 | Close | SL |
| SELL CE | ✅ | ❌ | 46.30 | 49.14 | 46.33 | Close | TP |
| SELL CE | ✅ | ❌ | 47.50 | 49.14 | 46.33 | Hold | Within range |
| SELL CE | ✅ | ❌ | 50.00 | 49.14 | 46.33 | Close | SL (> barrier) |
| SELL CE | ✅ | ✅ | — | — | — | Skip | Already closed |

---

## PER-LEG DEPENDENCY MATRIX

```
                SELL CE     SELL PE     BUY CE      BUY PE
SELL CE         —           ✅ Indep    ✅ Indep    ✅ Indep
SELL PE         ✅ Indep    —           ✅ Indep    ✅ Indep
BUY CE          ✅ Indep    ✅ Indep    —           ✅ Indep
BUY PE          ✅ Indep    ✅ Indep    ✅ Indep    —

Legend:
✅ Indep = Completely independent
        = Shared gate (none in current system)
```

**Key Finding:** NO leg depends on another leg's entry/exit.
- Each leg can trade independently
- One leg's failure doesn't block others
- Per-leg attempt tracking enables parallel processing

---

## EXAMPLE RUNTIME TRACE: Complete Trade Cycle

```
09:25:00.000 [STRATEGY_TRACE] phase=STANDBY → PHASE0, subscribe spot
09:29:15.234 [STRATEGY_TRACE] PHASE0 | SPOT=23950.00 | ATM=23900
09:29:30.567 [STRATEGY_TRACE] PHASE0 | SELL_CE | Ready | strike=23800 token=111111 ref=50.00
09:29:45.890 [STRATEGY_TRACE] PHASE0 | SELL_PE | Ready | strike=24000 token=222222 ref=51.50
09:29:46.000 [STRATEGY_TRACE] phase=PHASE0 → phase0_done=True

11:00:00.123 [STRATEGY_TRACE] phase=PHASE0 → PHASE1, delta selection starting
11:02:15.456 [STRATEGY_TRACE] PHASE1 | Subscribe CE options (attempt 1/3)
11:02:35.789 [STRATEGY_TRACE] PHASE1 | Delta data ready (60% collected)
11:02:40.012 [STRATEGY_TRACE] PHASE1 | BUY_CE | attempt=1 | Found delta=0.72 at 24100 | LOCKED
11:02:45.345 [STRATEGY_TRACE] PHASE1 | BUY_PE | attempt=2 | Delta mismatch | Retry
11:03:15.678 [STRATEGY_TRACE] PHASE1 | BUY_PE | attempt=2 | Found delta=0.71 at 23700 | LOCKED
11:03:16.000 [STRATEGY_TRACE] phase=PHASE1 → phase1_done=True, both hedges ready

14:15:00.000 [STRATEGY_TRACE] phase=PHASE1 → IN_TRADE

14:25:30.100 [STRATEGY_TRACE] ENTRY | SELL_CE | decay=3.20 >= trigger=3.00 | Place SELL
14:25:30.500 [STRATEGY_TRACE] ENTRY | SELL_CE | FILLED @ 46.80 | P&L_ref=50.00-46.80=3.20
14:25:31.100 [STRATEGY_TRACE] SELL_CE_entered=True, entry_price=46.80

14:26:15.200 [STRATEGY_TRACE] ENTRY | SELL_PE | decay=3.40 >= trigger=3.00 | Place SELL
14:26:15.600 [STRATEGY_TRACE] ENTRY | SELL_PE | FILLED @ 48.10 | P&L_ref=51.50-48.10=3.40
14:26:16.200 [STRATEGY_TRACE] SELL_PE_entered=True, entry_price=48.10

14:27:45.300 [STRATEGY_TRACE] ENTRY | BUY_CE | appreciation=8.50 >= trigger=7.50 | Place BUY
14:27:45.700 [STRATEGY_TRACE] ENTRY | BUY_CE | FILLED @ 38.50 | Qty=25 @ 38.50
14:27:46.300 [STRATEGY_TRACE] BUY_CE_entered=True, entry_price=38.50

14:28:30.400 [STRATEGY_TRACE] ENTRY | BUY_PE | appreciation=5.30 >= trigger=4.50 | Place BUY
14:28:30.800 [STRATEGY_TRACE] ENTRY | BUY_PE | FILLED @ 35.30 | Qty=25 @ 35.30
14:28:31.400 [STRATEGY_TRACE] BUY_PE_entered=True, entry_price=35.30

[All 4 legs now ENTERED]

14:29:00.000 [STRATEGY_TRACE] Position: SELL_CE(46.80) + SELL_PE(48.10) - BUY_CE(38.50) - BUY_PE(35.30)

14:29:45.100 [STRATEGY_TRACE] EXIT | SELL_CE | ltp=49.15 >= sl=49.14 | Place BUY_TO_CLOSE
14:29:45.500 [STRATEGY_TRACE] EXIT | SELL_CE | FILLED @ 49.15 | P&L=(46.80-49.15)*25 = -1312.50
14:29:46.000 [STRATEGY_TRACE] SELL_CE_exited=True

14:30:00.000 [STRATEGY_TRACE] Hard exit triggered: Close remaining positions
14:30:05.234 [STRATEGY_TRACE] EXIT | SELL_PE | Force close @ 48.20 | P&L=(48.10-48.20)*25 = -250
14:30:05.680 [STRATEGY_TRACE] EXIT | BUY_CE | Force close @ 38.45 | P&L=(38.45-38.50)*25 = -125
14:30:06.120 [STRATEGY_TRACE] EXIT | BUY_PE | Force close @ 35.25 | P&L=(35.25-35.30)*25 = -125

[All positions CLOSED]

14:30:06.500 [STRATEGY_TRACE] phase=IN_TRADE → CLOSED
14:30:06.600 [STATE_SNAPSHOT] All legs exited. Daily P&L=(-1312.50)+(-250)+(-125)+(-125)=-1812.50
```

---

## KEY ARCHITECTURAL INSIGHTS

### Independence Enforcement
✅ **4 legs:** Each has separate {token, price, entry_price, sl, tp, entered, exited}  
✅ **No shared variables** between legs (except phase0_done, phase1_done at completion)  
✅ **Thread-safe updates** via state.set() atomically  

### Feedback Mechanisms
✅ **Price feedback:** _on_tick() → snapshot update (0-100ms latency)  
✅ **Decision feedback:** *_entered flag set → notifier callback  
✅ **Order feedback:** Order API → result status → state.set() immediately  

### Failover Resilience
✅ **Phase 0 fails:** System gracefully enters Phase 1 with old SELL legs (if any)  
✅ **One BUY leg fails:** Other can still lock (per-leg attempt tracking)  
✅ **Entry blocked:** Continues checking until phase closed  
✅ **Exit fails:** Next loop rechecks conditions  

---

## CONFIGURATION PARAMETERS REFERENCED

```
Config.PHASE0_START = 09:25 IST
Config.PHASE0_END = 11:00 IST
Config.PHASE1_START = 11:00 IST
Config.PHASE1_END = 14:15 IST
Config.SQUAREOFF_TIME = 14:30 IST

Config.ATM_ROUND = 100 (strike rounding)
Config.DELTA_SCAN_RANGE = 5 (strike range multiplier)
Config.SELL_CE_OFFSET = 100 (offset from ATM)
Config.SELL_PE_OFFSET = 100 (offset from ATM)

Config.TARGET_CE_DELTA = 0.35 (PHASE0/1 selection)
Config.TARGET_PE_DELTA = 0.35

Config.SELL_DECAY_TRIGGER = 3.0 (entry trigger Rs)
Config.SELL_SL_PERCENT = 0.05 (5% SL)
Config.SELL_TP_PERCENT = 0.01 (1% TP)

Config.BUY_TRIGGER_MULTIPLIER = 1.5x
Config.BUY_TRIGGER_ABSOLUTE = +5.0 Rs
Config.BUY_SL_POINTS = 10 (Rs point loss)
Config.BUY_TP_POINTS = 20 (Rs point gain)

Config.PHASE1_MAX_ATTEMPTS = 3 (global safety)
Config.PHASE1_MAX_ATTEMPTS_PER_LEG = 30 (independent leg limit)
Config.PHASE1_DATA_WAIT_SECONDS = 20 (delta wait timeout)
Config.PHASE1_DATA_CHECK_INTERVAL = 0.5 (check frequency)
Config.PHASE1_RETRY_DELAY = 3 (delay between attmpts)

Config.LOTS = 1 (number of lots to trade)
Config.TRADING_MODE = "PAPER" (or "LIVE")
Config.DATA_MODE = "LIVE" (or "REPLAY")

Config.TRAILING_OBSERVATION_START = 12:00
Config.TRAILING_OBSERVATION_END = 14:00 (freeze point)
Config.TRAILING_ACTIVATION_TIME = 14:15
Config.TRAILING_BUFFER_PERCENT = 0.02 (2% buffer)
```

---

## CONCLUSION

The strategy employs a **highly modular, thread-safe architecture** with:
1. **Independent leg processing:** Each leg manages entry/exit independently  
2. **Per-leg attempt tracking:** Phase 1 can retry each BUY leg up to 30 times
3. **Time-based gating:** Phase transitions controlled by IST clock  
4. **Safety enforcement:** 7 validation requirements before actions  
5. **Graceful degradation:** System completes even if some hedges fail  

**Status:** ✅ All diagrams, matrices, and examples created without modifying any logic.

