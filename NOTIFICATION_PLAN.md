# Trading System Notification Plan
**Trader Mobile Monitoring Strategy**  
*Focus: Actionable alerts, minimal alert fatigue, clear priority hierarchy*

---

## Overview

This plan organizes Telegram notifications into **5 alert categories** with distinct patterns:
- **One-time critical events** (high priority, immediate)
- **Periodic status updates** (low priority, informational)
- **State-change only alerts** (medium priority, filtered by deduplication)

---

## 1. System Startup Alerts ⚡
**Pattern:** ONE-TIME (on application initialization)  
**Urgency:** MEDIUM (confirms readiness, not action-required)

### Current Implementation
- ✅ Startup confirmation already sent when notifier starts

### Proposed Enhancement
```
Alert: "🟢 SYSTEM READY
├─ Mode: [LIVE/PAPER]
├─ Time: HH:MM:SS IST
├─ Broker: Angel One [Connected]
├─ Instruments: N loaded
└─ Ready for trading"
```

### Rationale
- **One-time:** System startup happens once per day
- **Purpose:** Confirms all components initialized before first trade
- **Mobile view:** Trader sees system is ready before market opens
- **Content:** Minimal—just status, not full config

### Optional Schedule Alerts
```
Additional ONE-TIME alerts:
├─ Market open reminder (09:15 IST)
├─ Phase 0 window starting (09:30 IST)
└─ Market close warning (15:30 IST)
```
*Only if trader opts into schedule notifications in config*

---

## 2. Error Alerts 🔴
**Pattern:** ONE-TIME (on error occurrence)  
**Urgency:** CRITICAL (action required immediately)

### Category A: Connection Errors
```
Alert: "❌ CONNECTION LOST
├─ Service: [WebSocket/API]
├─ Last LTP: HH:MM:SS
├─ Retry: [attempt N/M]
└─ Action: Check network
   (Auto-reconnecting...)"
```
- **Trigger:** WebSocket disconnect, API timeout, broker connection lost
- **Pattern:** ONE-TIME per occurrence (not repeatedly while reconnecting)
- **Recovery:** Send "✅ Connection restored" once online

### Category B: Critical Trade Errors
```
Alert: "❌ TRADE FAILED
├─ Leg: [BUY CE/SELL PE]
├─ Strike: 22000 CE
├─ Qty: 15
├─ Reason: [Insufficient margin/Order rejected]
└─ Action: Manual intervention needed"
```
- **Trigger:** Order rejection, insufficient funds, exchange circuit breaker
- **Pattern:** ONE-TIME per failed order
- **Action:** Trader may need to manually close position or adjust quantity

### Category C: Data Validation Errors
```
Alert: "❌ DATA ERROR
├─ Issue: [Missing LTP for token/Invalid strike]
├─ Token: 12345 (BUY CE)
├─ Status: [Paused/Skipped]
└─ Fix: Check instrument master"
```
- **Trigger:** Missing LTP > grace period, invalid strike selection, schema violation
- **Pattern:** ONE-TIME per error (with rate limiting to avoid spam)
- **Note:** These typically require manual config fixes

---

## 3. Trade Entry/Exit Alerts 📊
**Pattern:** ONE-TIME per trade (crucial business events)  
**Urgency:** HIGH (trader monitors these closely)

### Trade Entry Alert
```
Alert: "🟢 TRADE ENTRY
├─ Phase: Phase 1 (ATM strangle)
├─ Legs: 
│  ├─ BUY CE: 22000 @ ₹145 (Qty: 15)
│  └─ BUY PE: 22000 @ ₹150 (Qty: 15)
├─ Capital: ₹8,850 (margin reserved)
├─ Time: 09:47 IST
└─ Stop Loss: ATM ± 200 points (locked)"
```

**Triggers:**
- Phase 0 entry (strike selection)
  ```
  "🟡 PHASE 0: Strike Selected
  ├─ ATM: 21985
  ├─ Sell CE: 22000 @ implied vol 45%
  ├─ Sell PE: 22000 @ implied vol 44%
  └─ Awaiting Phase 1 entry..."
  ```

- Phase 1 entry (legs bought)
  ```
  "🟢 PHASE 1: Legs Acquired
  ├─ Entry prices locked
  ├─ SL: Fixed at entry ± buffer
  └─ Monitoring for exits..."
  ```

### Trade Exit Alert
```
Alert: "🔴 TRADE EXIT
├─ Reason: [Profit target hit/SL triggered/Hard exit]
├─ Legs closed:
│  ├─ SELL CE: @ ₹142 (loss ₹45)
│  ├─ BUY PE: @ ₹155 (profit +₹75)
│  └─ Position: CLOSED
├─ Trade P&L: +₹90 (minutes: 127)
├─ Time: 13:54 IST
└─ Capital: Freed (margin released)"
```

**Triggers:**
- Profit target achieved
- Stop loss hit
- Hard exit (end of trading day)
- Manual close by trader

### Lock Event Alert
```
Alert: "🔒 LEG LOCKED
├─ Leg: BUY CE (Strike 22000)
├─ Lock reason: [Reached max loss limit]
├─ Current P&L: -₹450 (on this leg)
├─ Action: This leg is now static
└─ Other legs: Still trading"
```
- **Pattern:** ONE-TIME per lock event
- **Reason:** Alerts trader that a specific leg has stopped trading (e.g., max loss)

---

## 4. P&L Updates 💰
**Pattern:** HYBRID (one-time milestone + periodic updates)  
**Urgency:** MEDIUM (informational, not action-required)

### A. One-Time P&L Milestones
```
Alert: "🎯 P&L MILESTONE
├─ Current: +₹2,500
├─ Cumulative (today): +₹5,200
├─ Status: 125% of daily target
└─ Recommendation: Consider closing"
```
- **Triggers:** 
  - Hit 100% of daily P&L target
  - Hit 150% of daily P&L target
  - Hit max daily loss (-50% of capital allocation)
  
- **Pattern:** ONE-TIME per milestone (deduplication by cache)

### B. Periodic P&L Snapshots (During IN_TRADE Phase Only)
```
Snapshot (every 5 minutes during active trade):
"📊 POSITION SNAPSHOT
├─ Phase: IN_TRADE (127 minutes)
├─ Active Legs: 4
│  ├─ SELL CE 22000: LTP ₹142 → P&L -₹45
│  ├─ BUY PE 22000: LTP ₹155 → P&L +₹75
│  ├─ [Locked legs]: 1 leg static
│  └─ [Closed legs]: 2 legs (partial exit)
├─ Current P&L: +₹90
├─ Max profit: +₹450 (at 12:15)
├─ Max loss: -₹120 (at 11:42)
└─ Greeks: IV=42%, Delta=-0.05"
```

- **Frequency:** Every 5-10 minutes (configurable; only if IN_TRADE)
- **Purpose:** Trader monitors position health over time
- **Content:** Only legs with meaningful changes since last snapshot
- **Deduplication:** Skip snapshot if P&L unchanged by > ₹10

---

## 5. Periodic Status Reports 📈
**Pattern:** PERIODIC (at fixed intervals during business hours)  
**Urgency:** LOW (background info, not action-required)

### Heartbeat Message (Daily)
```
Alert: "💓 HEARTBEAT (Daily)
├─ Date: 15-Feb-2026
├─ Trades executed: 3
├─ Daily P&L: +₹5,200
├─ Win rate: 75% (3 wins, 1 loss)
├─ Cumulative (YTD): +₹48,500
└─ Next: Market close at 15:30"
```

- **Frequency:** 1× per day (e.g., at 15:45 IST after market close)
- **Purpose:** Daily summary for trader review
- **Content:** Daily metrics only (no real-time data)

### Session Summary (On Demand)
```
// Not periodic, but sent on trader request
Alert: "📋 SESSION SUMMARY
├─ Trading Window: 09:30 - 15:30
├─ Phase transitions: 4
├─ Trades: 3 (2 wins, 1 loss)
├─ Capital deployed: ₹45,000 (peak)
├─ Final balance: ₹52,200
├─ Sharpe ratio (intra-day): 1.8
└─ Recommendation: [Based on daily stats]"
```

### Status Check (Optional Scheduled)
```
// Can be requested by trader at specific times:
- "What's my current balance?" → Real-time balance check
- "Show active legs" → Current position list
- "Daily stats" → Day's performance so far
```

---

## 6. Trailing Stop-Loss Updates 🎯
**Pattern:** ONE-TIME per stop-loss move (state-change only)  
**Urgency:** HIGH (active change in risk management)

```
Alert: "📍 STOP LOSS ADJUSTED
├─ Leg: SELL CE (Strike 22000)
├─ Reason: [Profit lock / Adverse price reached]
├─ Old SL: ₹150
├─ New SL: ₹145
├─ P&L protected at: +₹50 (minimum)
├─ Time: 13:15 IST"
```

- **Trigger:** Stop loss price changes (e.g., during trailing phase)
- **Pattern:** ONE-TIME per SL adjustment
- **Deduplication:** Only send if SL price changed (not on every calculation)

---

## 7. One-Time vs. Periodic Decision Matrix

| Event | Type | Frequency | When Sent |
|-------|------|-----------|-----------|
| **System Startup** | ONE-TIME | - | App initialization |
| **Connection Lost** | ONE-TIME | Per occurrence | On disconnect |
| **Connection Restored** | ONE-TIME | Per recovery | On reconnect |
| **Trade Entry** | ONE-TIME | Per trade | Phase 0 & Phase 1 entries |
| **Trade Exit** | ONE-TIME | Per trade | Profit/SL/hard exit hit |
| **Lock Event** | ONE-TIME | Per leg lock | When leg reaches limit |
| **Trailing SL Update** | ONE-TIME | Per SL change | When SL price moves |
| **P&L Milestone** | ONE-TIME | Per threshold | At 100%/150%/max-loss targets |
| **Position Snapshot** | PERIODIC | Every 5-10 min | Only during IN_TRADE phase |
| **Daily Heartbeat** | PERIODIC | 1× per day | Post-market close (15:45) |
| **Error Alert** | ONE-TIME | Per error | When exception occurs |

---

## 8. Trader's Mobile Monitoring Workflow

### Morning (Pre-Market: 09:00-09:30)
```
Trader checks phone:
1. ✅ System startup confirmation (was at 09:00)
2. ✅ Market reminder (was at 09:15)
3. Ready to trade
```

### During Trading (09:30-15:30)
```
Trader's phone activity:
- Receives 1 alert per trade entry (important)
- Receives 1 alert per trade exit (important)
- Receives position snapshot every 5-10 min (status check)
- If error: 1 alert (critical action)
- If SL adjustment: 1 alert (risk update)

Total expected alerts: 3-8 per day (moderate, not noisy)
```

### Evening (Post-Market: 15:30-16:00)
```
Trader reviews:
1. Daily heartbeat (auto-sent at 15:45)
2. All trade logs in chat history
3. Can request session summary if needed
```

---

## 9. Alert Frequency & Noise Control

### Current Approach: Deduplication
- **System Status:** Only send if status changes (login/WebSocket)
- **Phase Change:** Only send once per phase transition
- **Lock Events:** Only send once per lock (not repeated)
- **Trailing SL:** Only send if SL price actually changes
- **Snapshots:** Skip if P&L unchanged by > threshold (e.g., ₹10)

### Recommended Daily Alert Budget
```
Typical trading day (example):
├─ Startup + market open: 2 alerts
├─ Trade entries (2 trades): 2 alerts
├─ Trade exits (2 trades): 2 alerts
├─ Position snapshots (6-8 during day): 6-8 notifications
├─ Trailing SL updates (2-3): 2-3 alerts
├─ Daily heartbeat: 1 alert
└─ Total: 15-18 notifications (manageable, ~1-2 per 30 min)
```

**If > 5 alerts per hour:** Check for error spam or position churn

---

## 10. Implementation Roadmap

### Phase 1: Foundation (Already Exists)
- ✅ Entry/exit alerts
- ✅ Lock event alerts
- ✅ Trailing SL alerts
- ✅ Periodic snapshots
- ✅ Heartbeat mechanism

### Phase 2: Enhancements (Next Steps)
- [ ] Add system startup confirmation with mode/broker status
- [ ] Add error categorization (connection vs. trade vs. data)
- [ ] Add P&L milestone tracking (100%, 150%, max-loss)
- [ ] Add daily heartbeat summary (customizable time)
- [ ] Add deduplication for error spam (rate limit errors to 1 per 10 sec per type)

### Phase 3: Advanced (Optional)
- [ ] Multi-leg entry alert (consolidated view)
- [ ] Greek updates during IN_TRADE (IV changes, delta shifts)
- [ ] Recommendation engine ("Close now?" based on P&L/time-decay)
- [ ] Mobile commands: "Show balance", "Close position X", "Daily stats"

---

## 11. Example Mobile Alert Timeline (Single Trading Day)

```
09:00  🟢 [STARTUP] System ready, LIVE mode, Angel One connected
09:30  🟢 [SCHEDULE] Phase 0 window opened
09:45  🟡 [PHASE 0] Strike selected: CE=22000, PE=22000
09:47  🟢 [ENTRY] Phase 1: BUY CE ₹145, BUY PE ₹150 (Qty: 15)
10:00  📊 [SNAPSHOT] P&L +₹45, 4 active legs
10:15  📊 [SNAPSHOT] P&L +₹120, IV=41%
10:30  📊 [SNAPSHOT] P&L +₹95, Adverse price: IMA
10:45  📍 [TRAILING SL] SELL CE SL adjusted to ₹152
11:00  📊 [SNAPSHOT] P&L +₹180, 2 locked
11:15  📊 [SNAPSHOT] P&L +₹165
...
13:50  🔴 [EXIT] Profit target hit: P&L +₹450, trade closed
14:00  ✅ [MILESTONE] +₹450 (150% of daily target) 
15:45  💓 [HEARTBEAT] Daily summary: 3 trades, +₹5,200 P&L, 75% win rate
```

---

## 12. Configuration Recommendations

### config.py additions
```python
# Notification settings
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"

# Alert patterns
NOTIFY_STARTUP = True
NOTIFY_ERRORS = True                    # Critical
NOTIFY_ENTRIES = True                   # One-time per trade
NOTIFY_EXITS = True                     # One-time per trade
NOTIFY_SL_CHANGES = True                # One-time per SL move
NOTIFY_PNL_MILESTONES = True            # At 100%, 150%, max-loss

# Periodic alerts (set to 0 to disable)
SNAPSHOT_INTERVAL_SECONDS = 300         # 5 minutes during IN_TRADE
HEARTBEAT_TIME = "15:45"                # Daily summary (IST)
HEARTBEAT_ENABLED = True

# Deduplication thresholds
SNAPSHOT_PNL_THRESHOLD = 10             # Skip snapshot if P&L change < ₹10
ERROR_RATE_LIMIT_SECONDS = 10           # Max 1 error alert per 10 sec per type
```

---

## 13. Success Metrics

When plan is fully implemented:

| Metric | Target | How to Verify |
|--------|--------|---------------|
| **Alert Accuracy** | 99% (no false alerts) | Check chat logs vs. actual trades |
| **Alert Timeliness** | < 2 sec latency | Compare alert timestamp vs. log timestamp |
| **Deduplication** | 0 duplicate alerts | No repeated alerts for same event |
| **Daily Alert Count** | 15-20 (moderate) | Count unique notifications per day |
| **Error Coverage** | 100% of critical errors | Confirm all failures generate alerts |
| **Mobile Usability** | Actionable in < 10 sec | Trader can read & act without app |

---

## Summary

| Category | Pattern | Frequency | Key Alerts |
|----------|---------|-----------|-----------|
| **Startup** | One-time | 1× per session | System ready confirmation |
| **Errors** | One-time | Per occurrence | Connection/trade/data errors |
| **Entries** | One-time | Per trade | Strike selection, phase entries |
| **Exits** | One-time | Per trade | Profit/SL/hard exits |
| **P&L Updates** | Hybrid | Milestones + periodic | Snapshots every 5 min, milestones at 100%/150% |
| **Status** | Periodic | Daily | Heartbeat at market close |
| **SL Updates** | One-time | Per change | Trailing SL adjustments |

**Total daily alerts: 15-20 (low fatigue, high signal-to-noise)**

---

## Next Steps

1. **Review** this plan with trading team
2. **Customize** frequencies based on trader preferences (snapshot interval, heartbeat time)
3. **Implement Phase 2** enhancements
4. **Test** on paper trading first (verify alert timing/accuracy)
5. **Deploy** to live with monitoring for 1 week
6. **Iterate** based on trader feedback (too many alerts? Missing ones?)
