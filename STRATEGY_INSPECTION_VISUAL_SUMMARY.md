# STRATEGY INSPECTION – VISUAL SUMMARY

**Status:** ✅ Complete Read-Only Documentation  
**Date:** February 15, 2026  

---

## DOCUMENT STRUCTURE MAP

```
┌──────────────────────────────────────────────────────────────┐
│  STRATEGY LOGIC INSPECTION – COMPLETE DELIVERY               │
│  (2,500+ lines documentation, 0 code modifications)          │
└────────────────────┬─────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┬──────────────┐
        │            │            │              │
        ▼            ▼            ▼              ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐
   │STRAT    │  │STRAT     │  │STRAT     │  │DELIVERY│
   │LOGIC    │  │FLOW      │  │INSPECTION│  │SUMMARY │
   │INSPECT  │  │DIAGRAMS  │  │INDEX     │  │        │
   │1200 ln  │  │900 ln    │  │400 ln    │  │400 ln  │
   └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬───┘
        │            │             │             │
        │            │             │             │
   6 Q&A │      5 DIAGRAMS│   NAVIGATION│  STATUS & │
   TABLES│      + 4 MATRICES    CHECKLIST  DELIVERY │
   FLOW  │      + EXAMPLES      QUICK REF
   LOGIC │                      METRICS
```

---

## QUICK REFERENCE: WHAT EACH DOCUMENT ANSWERS

```
QUESTION                          DOCUMENT                    SECTION/TABLE
═══════════════════════════════════════════════════════════════════════════

Q1: Which methods run main         STRATEGY_LOGIC_INSPECTION   Q1 + Topology
    strategy loop?                 STRATEGY_FLOW_DIAGRAMS      Diagram 1

Q2: How are entries/exits          STRATEGY_LOGIC_INSPECTION   Q2
    triggered per leg?             STRATEGY_FLOW_DIAGRAMS      Diagrams 4-5
                                                               Matrices 1-3

Q3: Where are deltas & LTPs        STRATEGY_LOGIC_INSPECTION   Q3
    read to make decisions?        (Complete data source map)

Q4: How are phase                  STRATEGY_LOGIC_INSPECTION   Q4
    transitions handled?           STRATEGY_FLOW_DIAGRAMS      Diagrams 2-3

Q5: What runtime flags            STRATEGY_LOGIC_INSPECTION   Q5 + Tables
    control per-leg               (9 flag categories,
    readiness?                     100+ fields)

Q6: Where are safety              STRATEGY_LOGIC_INSPECTION   Q6 + Tables
    validations applied?          (7 requirements,
                                   retry delays)
```

---

## SYSTEM ARCHITECTURE AT A GLANCE

```
┌─────────────────────────────────────────────────────────────┐
│ MAIN PROCESS / StrategyEngine                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ FEED: Async Ticks (SmartConnect, Replay)            │   │
│  │ _on_tick(token, symbol, ltp, delta) [Async]         │   │
│  │   └─→ instruments.update_snapshot() [Sync]          │   │
│  │       └─→ All decisions read from snapshots         │   │
│  └─────────────────────────────────────────────────────┘   │
│           ▲                                                  │
│           │ Updates every tick                              │
│           │                                                  │
│  ┌────┬───┼────────────┬────────────┬─────────┬──────────┐  │
│  │    │   │            │            │         │          │  │
│  ▼    ▼   ▼            ▼            ▼         ▼          ▼  │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │   │
│ │ Thread 1:    │ │ Thread 2:    │ │ Thread 3:    │ ...  │   │
│ │ _phase_      │ │ _entry_      │ │ _exit_       │      │   │
│ │ monitor()    │ │ monitor()    │ │ monitor()    │      │   │
│ │             │ │             │ │             │      │   │
│ │ 09:25-14:30 │ │ Continuous  │ │ IN_TRADE     │      │   │
│ │ Time-based   │ │ loop with   │ │ only         │      │   │
│ │ state        │ │ safety      │ │             │      │   │
│ │ machine      │ │ validators  │ │             │      │   │
│ │             │ │             │ │             │      │   │
│ │ Selects:     │ │ Triggers:   │ │ Monitors:    │      │   │
│ │ SELL legs    │ │ Entry decay │ │ SL/TP/       │      │   │
│ │ BUY legs     │ │ appreciation│ │ trailing     │      │   │
│ └──────────────┘ │             │ │             │      │   │
│                  │ Locks:      │ │ Exits when  │      │   │
│                  │ *_entered   │ │ conditions  │      │   │
│                  │ flags       │ │ hit         │      │   │
│                  └──────────────┘ └──────────────┘      │   │
│                                                          │   │
│  Thread 4: _squareoff_monitor() | Thread 5: _heartbeat │   │
│  Thread 6: _trailing_observation_monitor()              │   │
│                                                          │   │
└─────────────────────────────────────────────────────────┘   │
       │                                                      │
       └──────────┬──────────────────────────────────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ STATE.json       │
         │ (Persistent)     │
         │                  │
         │ ├─ phase         │
         │ ├─ *_leg_ready   │
         │ ├─ *_entered      │
         │ ├─ *_exited       │
         │ ├─ *_attempts     │
         │ └─ ... (30+ fields)
         └──────────────────┘
```

---

## DECISION FLOW SUMMARY

```
ENTRY DECISION (Independent per leg):

SELL CE:                           BUY CE:                      BUY PE:
sell_ce_leg_ready? ───Yes──→       buy_ce_leg_ready? ───Yes──→  buy_pe_leg_ready?
   │                              │                           │
   No                             No                          No
   │                              │                           │
   ▼                              ▼                           ▼
  Skip                    decay = ref - ltp         ltp >= (ref × 1.5) + 5.0
                          >= 3.0 ?
                          ───Yes──→ Place SELL      ───Yes──→ Place BUY
                          │
                          No
                          │
                          ▼
                         Skip

EXIT DECISION (Independent per leg):

SELL CE (Fixed SL + Optional Trailing [14:15+]):
  └─ Fixed SL = entry × 1.05
  └─ IF 14:15+: trailing_sl = adverse × 1.02 (if tightens)
  └─ ltp >= SL? → Exit [SL]
  └─ ltp <= TP? → Exit [TP]

BUY CE (Fixed SL only):
  └─ SL = entry - 10 points
  └─ TP = entry + 20 points
  └─ Same logic as SELL (SL/TP check)
```

---

## PHASE PROGRESSION TIMELINE

```
09:15                 09:25                 11:00               14:15        14:30      15:30
  │                     │                     │                  │           │          │
  ├─ STANDBY ──────────┼── PHASE0 ──────────┼── PHASE1 ────────┼ IN_TRADE ──┼─ CLOSED
  │                     │                     │                  │           │
  │                     │ (ITM Selection)    │ (OTM Selection)   │ (Trading)  │
  │                     │                     │                  │           │
  │ Subscribe SPOT      │ Lock SELL CE/PE    │ Lock BUY CE/PE   │ Entry/Exit │ Force Close
  │                     │ phase0_done=True   │ phase1_done=True │ Monitors   │ All Positions
  │                     │                     │ Per-leg retry    │ Hard Exit  │
  │                     │                     │ (30 each leg)    │           │
  └─────────────────────┴─────────────────────┴──────────────────┴───────────┴───────────

Key Flags:
  Phase 0: phase0_done = False → True
           sell_ce_leg_ready = False → True
           sell_pe_leg_ready = False → True

  Phase 1: phase1_done = False → True (or partially if 1+ leg fails)
           buy_ce_leg_ready = False → True (or stays False, attempt tracked)
           buy_pe_leg_ready = False → True (or stays False, attempt tracked)
           _phase1_buy_ce_attempts: 0 → 30 (max)
           _phase1_buy_pe_attempts: 0 → 30 (max)

  In Trade: *_entered: False → True (as orders fill)
            *_exited: False → True (as positions close)

  Closed: All *_exited = True
          phase = CLOSED
```

---

## DATA FLOW DIAGRAM

```
┌─────────────────────────────┐
│ Broker API                   │
│ (SmartConnect Live/Replay)   │
│                              │
│ Every Tick:                  │
│ {token, ltp, delta,          │
│  gamma, theta, vega, ...}    │
└────────────────┬─────────────┘
                 │ Async
                 ▼
        ┌──────────────────┐
        │ Feed._on_tick()  │
        │ (Callback Async) │
        └────────┬─────────┘
                 │
                 ▼ Sync call
        ┌──────────────────────────┐
        │ instruments.             │
        │ update_snapshot()        │
        │                          │
        │ snapshot[token] = {      │
        │   'ltp': X.XX,           │
        │   'delta': Y.YY,         │
        │   'gamma': ...,          │
        │   'timestamp': ...       │
        │ }                        │
        └──────────┬───────────────┘
                   │ Single source of truth
        ┌──────────┴──────────────────────────────┐
        │                                         │
        ▼                                         ▼
   Entry Monitors                         Exit Monitors
   (@ each loop)                          (@ each loop)
   │                                      │
   ├─ _check_sell_entry()                 ├─ _check_sell_exit()
   │  get_ltp(token)                      │  get_ltp(token) [no delay]
   │  get_snapshot(token)['ltp']          │  calc_sl_from(entry_price)
   │  decay = ref - ltp                   │  calc_trailing_sl(adverse)
   │  => Place order if trigger met       │  => Exit if SL/TP hit
   │                                      │
   ├─ _check_buy_entry()                  └─ _check_buy_exit()
   │  get_ltp(token)                         [Same logic]
   │  ltp >= trigger => Place order
```

---

## INDEPENDENCE VERIFICATION

```
4 LEGS - ZERO SHARED PROCESSING:

SELL CE          SELL PE          BUY CE          BUY PE
├─ Token         ├─ Token          ├─ Token        ├─ Token
├─ Strike        ├─ Strike         ├─ Strike       ├─ Strike
├─ Symbol        ├─ Symbol         ├─ Symbol       ├─ Symbol
├─ Ref Premium   ├─ Ref Premium    ├─ Ref Premium  ├─ Ref Premium
├─ Entry Price   ├─ Entry Price    ├─ Entry Price  ├─ Entry Price
├─ SL Level      ├─ SL Level       ├─ SL Level     ├─ SL Level
├─ TP Level      ├─ TP Level       ├─ TP Level     ├─ TP Level
├─ Entered Flag  ├─ Entered Flag   ├─ Entered Flag ├─ Entered Flag
├─ Exited Flag   ├─ Exited Flag    ├─ Exited Flag  ├─ Exited Flag
│                │                 │                │
│ ZERO COUPLING  │ ZERO COUPLING   │ ZERO COUPLING │ ZERO COUPLING
│ Entry/exit     │ Entry/exit      │ Entry/exit    │ Entry/exit
│ independent    │ independent     │ independent   │ independent
│ from PE        │ from CE         │ from PE       │ from CE
│                │                 │               │
└─ Lock time:    └─ Lock time:     └─ Lock time:   └─ Lock time:
  09:25+           09:25+           11:00+          11:00+
  (attempt 1)      (attempt 1)      (30 attempts   (30 attempts
  Not retried      Not retried       possible)      possible)
```

---

## SAFETY VALIDATORS (7 Requirements)

```
┌─────────────────────────────────────────────────────────────┐
│ SAFETY VALIDATORS OVERVIEW (utils/safety_validator.py)      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. BROKER POSITION RECONCILIATION                            │
│    ├─ When: Before every entry monitor cycle                │
│    ├─ Check: state.trade_state vs broker.positions          │
│    ├─ Trigger: Mismatch → Block entries [5s delay retry]    │
│                                                              │
│ 2. STOP-LOSS VERIFICATION AFTER ENTRY                       │
│    ├─ When: Post-order FILLED                               │
│    ├─ Check: SL order exists at broker                      │
│    ├─ Trigger: Missing → Warn, continue (async creation)    │
│                                                              │
│ 3. RESTART RECOVERY                                          │
│    ├─ When: engine.start()                                  │
│    ├─ Check: Open positions at broker on startup            │
│    ├─ Action: Rebuild leg state from broker positions       │
│                                                              │
│ 4. LEG INDEPENDENCE VERIFICATION                            │
│    ├─ When: Before entry monitor processes                  │
│    ├─ Check: No cross-leg dependencies violated             │
│    ├─ Trigger: Violation → Block entries [5s delay retry]   │
│                                                              │
│ 5. DELTA LOOP SAFETY                                         │
│    ├─ When: Phase1 waiting for delta data                   │
│    ├─ Check: Timeout (20s) OR retry limit (2)               │
│    ├─ Trigger: Exceeded → Exit attempt [3s delay retry]     │
│                                                              │
│ 6. LTP UNAVAILABILITY SAFEGUARDS                            │
│    ├─ When: Entry/exit checking LTP                         │
│    ├─ Grace: 10s after subscription for first tick          │
│    ├─ Action: Silently skip during grace, warn after         │
│                                                              │
│ 7. HARD EXIT ENFORCEMENT                                    │
│    ├─ When: 14:30 IST or manual override                    │
│    ├─ Action: Force close ALL open positions                │
│    ├─ Effect: Non-recoverable (requires restart)            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## TRACE FORMAT SPECIFICATION

```
┌─────────────────────────────────────────────────────┐
│ RUNTIME TRACE FORMAT                                │
├─────────────────────────────────────────────────────┤
│                                                     │
│ [STRATEGY_TRACE] HH:MM:SS.mmm | PHASE | LEG |     │
│                  DECISION | DETAILS | ORDER_INFO   │
│                                                     │
├─────────────────────────────────────────────────────┤
│ EXAMPLES:                                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Phase Entry:                                       │
│ [STRATEGY_TRACE] 09:25:00.234 | PHASE0 | — |      │
│   PHASE_TRANSITION | from=STANDBY to=PHASE0 |     │
│   subscribe_spot                                   │
│                                                     │
│ Leg Locking:                                       │
│ [STRATEGY_TRACE] 09:30:15.567 | PHASE0 |          │
│   SELL_CE | LOCKED | strike=23900 delta=0.35 |    │
│   token=111111                                     │
│                                                     │
│ Entry Trigger:                                     │
│ [STRATEGY_TRACE] 14:25:30.100 | IN_TRADE |        │
│   SELL_CE | ENTRY_TRIGGERED | decay=3.2           │
│   ref=50.00 ltp=46.80 trigger=3.00 | BUY qty=25   │
│   @ Rs46.80 order_status=FILLED                    │
│                                                     │
│ Exit Trigger:                                      │
│ [STRATEGY_TRACE] 14:29:45.300 | IN_TRADE |        │
│   SELL_PE | EXIT_SL | ltp=52.75 sl=52.50 |        │
│   SELL_TO_CLOSE qty=25 @ Rs52.75 P&L=-1250        │
│                                                     │
│ Hard Exit:                                         │
│ [STRATEGY_TRACE] 14:30:00.678 | CLOSED | ALL |    │
│   HARD_EXIT | time=14:30 reached | FORCE_CLOSE    │
│   all_remaining_positions                          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## QUICK DECISION TREE

```
Entry Decision Tree:

Is leg ready? ──No──→ Skip entry check (not time yet)
  │
  Yes
  │
├─ SELL CE/PE:
│  │
│  decay = ref - ltp
│  │
│  decay >= 3.0? ──No──→ Skip (wait for more decay)
│    │
│    Yes
│    │
│    └──→ Place SELL order
│         │
│         FILLED? ──No──→ Will retry next cycle
│           │
│           Yes
│           │
│           └──→ Mark *_entered = True
│
└─ BUY CE/PE:
   │
   trigger = (ref × 1.5) + 5.0
   │
   ltp >= trigger? ──No──→ Skip (wait for appreciation)
     │
     Yes
     │
     └──→ Place BUY order
          │
          FILLED? ──No──→ Will retry next cycle
            │
            Yes
            │
            └──→ Mark *_entered = True
```

---

## CONFIGURATION AT A GLANCE

```
TIMING WINDOWS:
Phase0: 09:25 - 11:00   (95 minutes)
Phase1: 11:00 - 14:15   (195 minutes)
Trading: 14:15 - 14:30  (15 minutes)
Hard Exit: 14:30+

DECISION TRIGGERS:
SELL Decay: ≥ 3.0 Rs
BUY Trigger: (ref × 1.5) + 5.0 Rs
SELL SL: entry × 1.05 (5%)
SELL TP: entry × 0.99 (1%)
BUY SL: entry - 10 points
BUY TP: entry + 20 points

ATTEMPT LIMITS:
Phase1 Global: 3 attempts
Phase1 Per-Leg: 30 attempts each
Delta Wait: 20 seconds
Broker Recon Retry: 5 seconds (delay)

TRAILING SL (14:15+):
Observation: 12:00-14:00 (track highest price)
Freeze: 14:00 (lock observed price)
Neutral Gap: 14:00-14:15 (use fixed SL, no trailing)
Activation: 14:15+ (use trailing if tightens risk)
Buffer: 2% above adverse price
```

---

## DOCUMENT USAGE FLOW

```
START
  │
  ├─→ Want overview?
  │   └─→ Read DELIVERY_SUMMARY.md (10 min)
  │
  ├─→ Need all details?
  │   └─→ Read STRATEGY_LOGIC_INSPECTION.md (30 min)
  │
  ├─→ Want visual flows?
  │   └─→ Read STRATEGY_FLOW_DIAGRAMS_AND_MATRICES.md (20 min)
  │
  ├─→ Need specific info?
  │   └─→ Use STRATEGY_LOGIC_INSPECTION_INDEX.md (lookup)
  │
  ├─→ Ready to trace live?
  │   └─→ Use trace format from STRATEGY_LOGIC_INSPECTION.md
  │
  └─→ deploying to prod?
      └─→ Verify checklist in DELIVERY_SUMMARY.md

END
```

---

**All 6 Questions Answered | 5 Diagrams Provided | 4 Decision Matrices | Zero Code Changes**

