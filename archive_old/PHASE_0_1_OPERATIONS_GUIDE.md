# PHASE 0/1 CRITICAL WINDOW - OPERATIONS GUIDE

**Status:** ✓ LIVE READY  
**Last Updated:** 2026-02-15

---

## What This Does

Automatic failsafe that **prevents missed trades** during NSE market opening when WebSocket disconnects or data goes stale.

**Without this system:**
- 09:16:00: WebSocket disconnects  
- 09:16:02-09:16:45: Orders fail repeatedly
- Result: MISSED TRADES during critical window

**With this system:**
- 09:16:00: WebSocket disconnects   
- 09:16:00: Auto-reconnect starts (every 1 second)
- 09:16:02: Connection restored
- 09:16:03: Trading resumes
- Result: NO MISSED TRADES ✓

---

## When It Monitors (Critical Windows)

### Phase 0: 09:15:50 - 09:16:30 (40 seconds)
- Initial token subscriptions and data sync
- If WebSocket down → Auto-retry every 1 second

### Phase 1: 09:16:40 - 09:17:20 (40 seconds)
- Main order acceptance window  
- If data stale or WebSocket down → Auto-retry every 1 second

### Outside These Windows
- Normal monitoring (not critical phase protection)

---

## Reading the Logs

### Success Case (Ideal)
```
09:16:00.234 [CRITICAL] PHASE_0 CRITICAL RETRY STARTED - can_trade() returned False
09:16:01.456 [INFO] PHASE_0 Retry attempt #1/50 - can_trade() still False, waiting 1 second...
09:16:02.789 [INFO] PHASE_0 TRADING SAFE - resuming
```
**What: WebSocket was down, recovered after 2 attempts (2 seconds) ✓**

### Many Attempts (Investigate)
```
09:16:00.234 [CRITICAL] PHASE_0 CRITICAL RETRY STARTED
[... attempts #1 through #10 ...]
09:16:11.456 [INFO] PHASE_0 TRADING SAFE - resuming
```
**What: Feed took 11 seconds to recover, indicates latency issue ⚠️**

### Phase Ended Before Recovery
```
09:16:25.234 [CRITICAL] PHASE_0 CRITICAL RETRY STARTED
[... attempts #1 through #4 ...]
09:16:31.890 [WARNING] PHASE_0 window ended, resuming after 4 attempts
```
**What: Feed was still down when Phase 0 window ended ⚠️**

### Orders Blocked
```
09:16:15.234 [ERROR] ORDER BLOCKED [PHASE_0]: can_trade() returned False (blocked attempt #1)
09:16:17.456 [ERROR] ORDER BLOCKED [PHASE_0]: can_trade() returned False (blocked attempt #2)
09:16:21.890 [INFO] PHASE_0 TRADING SAFE - resuming
```
**What: Feed was down, 2 orders were blocked, system recovered after ~6+ seconds ⚠️**

---

## Key Metrics to Monitor

### 1. Retry Count per Phase
- **Ideal:** 1-2 attempts (immediate recovery)
- **Acceptable:** 3-5 attempts
- **Warning:** 6-10 attempts (feed latency issue)
- **Alert:** >10 attempts (persistent problem)

### 2. Blocked Orders per Phase  
- **Ideal:** 0 (no orders blocked)
- **Acceptable:** 1-3 (minor missed orders)
- **Warning:** 4-10 (multiple missed trades)
- **Alert:** >10 (significant trading impact)

### 3. Recovery Time
- **Ideal:** < 3 seconds
- **Acceptable:** 3-5 seconds
- **Warning:** 5-10 seconds
- **Alert:** > 10 seconds (feed problem)

### 4. Phase Window Detection
- Should see PHASE_0 logs around 09:16:00-09:16:15
- Should see PHASE_1 logs around 09:17:00+
- If missing: May indicate phase detection not working

---

## Daily Checklist (During 09:15-09:17)

```
Time      Check                                Status
─────────────────────────────────────────────────────
09:16:00  See "CRITICAL RETRY" message?        ☐ Yes  ☐ No
09:16:05  Retry count is 1-5?                   ☐ Yes  ☐ No
09:16:10  See "TRADING SAFE"?                   ☐ Yes  ☐ No
09:16:15  Trading resumed normally?             ☐ Yes  ☐ No
───────────────────────────────────────────────────
09:17:00  See "PHASE_1 CRITICAL RETRY"?         ☐ Yes  ☐ No
09:17:05  Retry count is 1-5?                   ☐ Yes  ☐ No
09:17:10  See "TRADING SAFE"?                   ☐ Yes  ☐ No
09:17:20  Trading normal after Phase 1?         ☐ Yes  ☐ No

If any are ☐ No, investigate:
→ Check feed connectivity
→ Review retry logs
→ Check phase detection
```

---

## Troubleshooting

### Issue: "Lots of retry attempts (>10)"
**Probable cause:** Feed connectivity problems
**Action:**
1. Check WebSocket connection status
2. Verify network to feed provider
3. Review feed subscription logs
4. Contact infrastructure if persists

### Issue: "High blocked attempt count (>5)"
**Probable cause:** Feed was down during critical phase
**Impact:** Some orders were prevented (missed trades)
**Action:**
1. Check feed status during Phase 0/1
2. Review retry count (how long was it down?)
3. Note time of issue for later analysis
4. If happens daily, escalate

### Issue: "No PHASE_0/PHASE_1 logs visible"
**Possible case 1:** No issues (everything worked fine) ✓
- This is actually ideal
- can_trade() was True all along
- No retry needed

**Possible case 2:** Phase detection broken
- Check: Is clock time in IST (UTC+5:30)?
- Check: Is current time in Phase 0 or Phase 1 window?
- Check: Are timestamp in logs showing 09:15-09:17 range?
- If issue persists, check engine.py _get_current_phase() function

### Issue: "Trading stopped during Phase 0"
**Diagnostics:**
1. Check for "ORDER BLOCKED" in logs → blocked attempts counter
2. Check for "CRITICAL RETRY" → indicates feed was down
3. Check retry count:
   - 1-5: Minor blip ✓
   - 6-20: Feed latency issue ⚠️
   - >20: Persistent problem ⚠️
4. If blocked attempts high: Some orders were prevented

---

## Emergency Actions

### If feed down >30 seconds in Phase window:
1. Check WebSocket logs for errors
2. Check network connectivity to feed provider
3. Verify feed service is running
4. If on staging: Can manually restart
5. If on production: Follow escalation procedure

### If system keeps missing trades every day:
1. Collect logs from last 5 days
2. Analyze retry counts trend
3. Check if issue is consistent time or random
4. Escalate with data to infrastructure team

### If phase detection seems broken:
1. Verify Config.PHASE0_START/END values
2. Check if current time is actually in Phase 0/1 window
3. Look at timestamps - are they showing 09:15-09:17?
4. If still broken: Code may need review

---

## Success Metrics (What Should Happen)

During normal operations:
- ✓ Phase 0 activates at 09:15:50
- ✓ Retry count is 1-2 (immediate success)
- ✓ Trading resumes by 09:16:02
- ✓ Zero blocked orders during Phase 0
- ✓ Phase 1 activates at 09:16:40
- ✓ Retry count is 1-2 (immediate success)
- ✓ Trading resumes by 09:16:42
- ✓ Zero blocked orders during Phase 1

If you see this: System is working perfectly ✓

---

## When to Escalate

Create an incident if:
- ❌ Retry count > 25 in single phase (can't recover)
- ❌ System blocked >20 orders in one day (massive impact)
- ❌ "window ended, resuming" happens every single day
- ❌ "PHASE_0 CRITICAL" never appears (detection broken)
- ❌ Trading dropped from normal to zero during 09:16-09:17

**Include in escalation:**
1. Date/time of issue
2. Retry count (if applicable)
3. Blocked order count
4. Log snippet showing the issue

---

## Three Key Points

1. **This is insurance:** If feed breaks during Phase 0/1, system auto-retries every 1 second for 50 seconds. Prevents missed trades.

2. **Only for critical windows:** 09:15:50-09:16:30 and 09:16:40-09:17:20. Rest of day uses normal monitoring.

3. **Not a root-cause fix:** If you see >10 retries daily, the feed has deeper issues. This masks it, doesn't solve it. Needs investigation.

---

## Support

For issues:
1. Get log snippet from 09:15-09:17 timeframe with timestamp
2. Note retry count and blocked order count
3. Include your observations
4. Contact support team with subject: "PHASE_0/1 Critical Window Issue"

---

**Deployment Status:** ✓ READY FOR LIVE TRADING
