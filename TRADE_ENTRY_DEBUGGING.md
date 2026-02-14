# 🔍 Trade Entry Debugging Guide

## Why Trades Don't Execute - Complete Troubleshooting

This guide explains **every possible reason** why the system might not enter trades, even when you think conditions are met.

---

## 📋 Quick Diagnostic Checklist

Run this checklist first:

```bash
# Run the diagnostic script
python diagnose_trade_entry.py
```

Then check:
- [ ] No kill switches enabled
- [ ] Phases completing on time
- [ ] Legs marked as ready
- [ ] LTP data available
- [ ] Entry conditions actually met
- [ ] Current time in trading window

---

## 🎯 The Entry Flow (What Must Happen)

### Step 1: Phase 0 (09:15:50 - 09:16:10)
**What happens:** System selects SELL CE and SELL PE strikes

**Requirements:**
- ✅ Spot LTP available
- ✅ ATM calculation works
- ✅ Strike selection completes
- ✅ Tokens subscribed to WebSocket
- ✅ Reference premiums captured

**How to verify:**
```python
# Check state file
{
  "phase0_done": true,
  "sell_ce_leg_ready": true,
  "sell_pe_leg_ready": true,
  "sell_ce_token": "...",
  "sell_pe_token": "...",
  "sell_ce_ref_premium": 150.0,
  "sell_pe_ref_premium": 148.0
}
```

**If Phase 0 fails:**
- Check logs for "PHASE0" messages
- Verify spot token is subscribed
- Check WebSocket connection
- Verify CSV file has instrument data

---

### Step 2: Phase 1 (09:16:15 - 09:16:45)
**What happens:** System selects BUY CE and BUY PE strikes (hedges)

**Requirements:**
- ✅ Delta calculation works
- ✅ OTM strike selection completes
- ✅ Tokens subscribed
- ✅ Reference premiums captured

**How to verify:**
```python
{
  "phase1_done": true,
  "buy_ce_leg_ready": true,
  "buy_pe_leg_ready": true,
  "buy_ce_token": "...",
  "buy_pe_token": "...",
  "buy_ce_ref_premium": 32.0,
  "buy_pe_ref_premium": 29.0
}
```

**If Phase 1 fails:**
- Check logs for "PHASE1" messages
- Verify delta calculation is working
- Check OTM range is reasonable
- Ensure Phase 1 window is long enough (30s default)

---

### Step 3: Entry Delay (After 09:16:45)
**What happens:** System waits SELL_ENTRY_DELAY seconds

**Requirements:**
- ✅ Wait period must complete
- ✅ Time must be >= Phase1_end + delay

**Current delay:** Check `Config.SELL_ENTRY_DELAY` (default: 1.0s)

**If delay is too long:**
- Reduce `SELL_ENTRY_DELAY` in config
- Typical range: 0.5 - 2.0 seconds

---

### Step 4: Entry Condition Check (Continuous)
**What happens:** System checks if entry conditions are met

**SELL Entry Condition:**
```python
decay = ref_premium - current_ltp
condition = decay >= SELL_DECAY_TRIGGER

# Example:
# ref_premium = 150.0
# SELL_DECAY_TRIGGER = 2.0
# If LTP = 147.5: decay = 2.5 → ✅ ENTER
# If LTP = 148.5: decay = 1.5 → ❌ WAIT
```

**BUY Entry Condition:**
```python
trigger = (ref_premium * BUY_TRIGGER_MULTIPLIER) + BUY_TRIGGER_ABSOLUTE
condition = current_ltp >= trigger

# Example:
# ref_premium = 32.0
# BUY_TRIGGER_MULTIPLIER = 1.8
# BUY_TRIGGER_ABSOLUTE = 2.0
# trigger = (32.0 * 1.8) + 2.0 = 59.6
# If LTP = 60.0: ✅ ENTER
# If LTP = 58.0: ❌ WAIT
```

---

### Step 5: Order Placement
**What happens:** System places order via broker

**Requirements:**
- ✅ Broker API working
- ✅ Sufficient margin
- ✅ Valid token/symbol
- ✅ Valid quantity

**If order fails:**
- Check broker logs
- Verify credentials
- Check margin requirements
- Verify lot size is valid

---

## 🚨 Top 10 Reasons Trades Don't Execute

### 1. Kill Switch Enabled ⚡
**Symptom:** System starts but never trades

**Check:**
```python
# In config.py or .env
KILL_SWITCH_ENABLED=false  # Must be false
NO_NEW_TRADES=false        # Must be false
```

**Fix:** Set both to `false`

---

### 2. Phases Not Completing ⏰
**Symptom:** Legs never marked ready

**Check state file:**
```json
{
  "phase0_done": false,  // ❌ Phase 0 failed
  "phase1_done": false   // ❌ Phase 1 failed
}
```

**Common causes:**
- WebSocket not connected
- LTP not available during phase windows
- Phase windows too short
- CSV file missing instruments
- Time sync issues

**Fix:**
- Enable DEBUG_MODE=true
- Check logs during 09:15-09:17
- Verify WebSocket connection
- Extend phase windows if needed

---

### 3. LTP Not Available 📊
**Symptom:** Logs show "LTP unavailable"

**What to check:**
```
[SELL_ENTRY_CHECK] CE LTP unavailable for token=12345
```

**Common causes:**
- WebSocket disconnected
- Tokens not subscribed
- Feed delay
- Invalid token

**Fix:**
- Check WebSocket status in logs
- Verify token subscription
- Check feed health monitoring
- Restart if WebSocket dead

---

### 4. Entry Conditions Never Met 📉
**Symptom:** Legs ready, but no entry

**Debug:**
Enable DEBUG_MODE and watch logs:
```
[SELL_ENTRY_CHECK] CE ref=150.00, ltp=149.00, decay=1.00, trigger=2.00, condition_met=False
```

**Analysis:**
- Decay is 1.0
- Trigger is 2.0
- Condition NOT met (decay < trigger)

**Fix options:**
1. **Lower decay trigger:**
   ```python
   SELL_DECAY_TRIGGER = 1.0  # Instead of 2.0
   ```

2. **Wait for more decay:**
   - Premium needs to drop more
   - May happen naturally

3. **Adjust reference timing:**
   - Reference might be captured at wrong time
   - Check Phase 0 timing

---

### 5. Entry Delay Too Long ⏱️
**Symptom:** Conditions met, then miss trade window

**What happens:**
- Condition met at 09:16:46
- But entry delay ends at 09:16:47
- By then, premium has moved
- Condition no longer met

**Fix:**
```python
SELL_ENTRY_DELAY = 0.5  # Reduce from 1.0
```

---

### 6. Wrong Time Window 🕐
**Symptom:** System not checking during market hours

**Check:**
```python
# In config.py
PHASE0_START = time(9, 15, 50)
PHASE0_END = time(9, 16, 10)
PHASE1_START = time(9, 16, 15)
PHASE1_END = time(9, 16, 45)
```

**Verify:**
- Times are in IST (Asia/Kolkata)
- Windows don't overlap incorrectly
- Current time falls in windows

---

### 7. Already Entered 🔒
**Symptom:** No entry logs, system seems idle

**Check state:**
```json
{
  "sell_ce_entered": true,  // Already in!
  "sell_pe_entered": true
}
```

**What happened:**
- Trade already executed
- System now monitoring exits
- Check exit monitor logs

---

### 8. Lot Size Zero 📦
**Symptom:** Order placement fails

**Check:**
```python
LOTS = 1  # Must be > 0

# Also check lot_size in state
{
  "lot_size": 50  // Must be valid
}
```

**Fix:**
- Set LOTS in config
- Verify lot_size is captured from CSV

---

### 9. Broker Rejection 🚫
**Symptom:** Entry condition met, order fails

**Logs show:**
```
[SELL_ENTRY_CHECK] ✅ CONDITION MET - Placing order
[SELL_ENTRY_CHECK] ❌ Order failed
```

**Common causes:**
- Insufficient margin
- Invalid symbol
- Broker API error
- Rate limit exceeded
- After market hours

**Fix:**
- Check broker logs
- Verify margin
- Check broker status
- Retry if transient error

---

### 10. State File Issues 💾
**Symptom:** Legs locked, but system doesn't remember

**Check:**
```bash
ls -la strategy_state.json
cat strategy_state.json
```

**Problems:**
- File not writable
- File corrupted
- State not persisting
- Race conditions

**Fix:**
- Check file permissions
- Delete and recreate
- Check for file locks
- Review state update logs

---

## 🔧 Debugging Workflow

### Step 1: Run Diagnostic
```bash
python diagnose_trade_entry.py > diagnostic_output.txt
```

Review the output for:
- ❌ Critical issues
- ⚠️ Warnings
- ℹ️ Information

### Step 2: Enable Debug Mode
```python
# In config.py or .env
DEBUG_MODE = true
```

### Step 3: Monitor Logs During Market Hours
Watch for:
```
[SELL_ENTRY_CHECK] messages
[PHASE0] messages
[PHASE1] messages
WebSocket status
LTP availability
Entry condition calculations
```

### Step 4: Check State Progression
```bash
# Before market open
cat strategy_state.json  # Should be empty or have old data

# After 09:16:10
cat strategy_state.json  # Should have phase0_done=true

# After 09:16:45
cat strategy_state.json  # Should have phase1_done=true

# After 09:17:00
cat strategy_state.json  # Should have entries if conditions met
```

### Step 5: Analyze Entry Conditions
Look at the logs for actual numbers:
```
[SELL_ENTRY_CHECK] CE ref=150.00, ltp=148.50, decay=1.50, trigger=2.00, condition_met=False
```

Calculate yourself:
- Is decay >= trigger?
- If no, how much more decay needed?
- Is this realistic given market conditions?

---

## 🎓 Understanding Entry Logic

### SELL Entry (Short Options)
```python
# We SELL when premium has DECAYED enough
ref_premium = 150.0  # Locked in Phase 0
current_ltp = 148.0  # Current market price
decay = ref_premium - current_ltp = 2.0

# Trigger
SELL_DECAY_TRIGGER = 2.0

# Condition
if decay >= SELL_DECAY_TRIGGER:
    ENTER_SELL_TRADE()
```

**Why this logic?**
- We want premium to decay before selling
- Ensures we get good entry price
- Reduces immediate loss risk

**If never triggering:**
- Premium isn't decaying enough
- Lower SELL_DECAY_TRIGGER
- Or wait longer

---

### BUY Entry (Long Options - Hedges)
```python
# We BUY when premium has SPIKED enough
ref_premium = 32.0  # Locked in Phase 1
multiplier = 1.8
absolute = 2.0
trigger = (32.0 * 1.8) + 2.0 = 59.6

current_ltp = 60.0

# Condition
if current_ltp >= trigger:
    ENTER_BUY_TRADE()
```

**Why this logic?**
- We want hedges when they're needed
- High premium = high volatility = need protection
- Ensures we don't buy unnecessary hedges

---

## 📊 Entry Condition Tuning

### Conservative Entry (Safer, Fewer Trades)
```python
SELL_DECAY_TRIGGER = 3.0  # Wait for more decay
BUY_TRIGGER_MULTIPLIER = 2.0  # Higher threshold
```

### Aggressive Entry (More Trades, More Risk)
```python
SELL_DECAY_TRIGGER = 1.0  # Enter sooner
BUY_TRIGGER_MULTIPLIER = 1.5  # Lower threshold
```

### Balanced (Default)
```python
SELL_DECAY_TRIGGER = 2.0
BUY_TRIGGER_MULTIPLIER = 1.8
BUY_TRIGGER_ABSOLUTE = 2.0
```

---

## 🚀 Quick Fixes

### Problem: Trades never execute
**Solution 1:** Lower decay trigger
```python
SELL_DECAY_TRIGGER = 1.0
```

**Solution 2:** Reduce entry delay
```python
SELL_ENTRY_DELAY = 0.5
```

**Solution 3:** Widen phase windows
```python
PHASE0_END = time(9, 16, 15)  # Give more time
PHASE1_END = time(9, 16, 50)  # Give more time
```

---

### Problem: Phases not completing
**Solution:** Check WebSocket
```
# Look in logs for:
WebSocket: CONNECTED
on_open called
Subscribed to tokens
```

If disconnected:
- Restart system
- Check network
- Verify credentials

---

### Problem: "LTP unavailable"
**Solution:** Wait for first tick
- New token subscription takes 1-2 seconds
- Grace period built in
- If persistent, check feed health

---

## 📝 Logging Best Practices

### Essential Logs to Monitor
1. **Phase progression:**
   ```
   PHASE0: ATM=24500, CE=24400, PE=24600
   PHASE1: OTM CE=24900, OTM PE=24100
   ```

2. **Leg readiness:**
   ```
   SELL CE leg ready
   SELL PE leg ready
   BUY CE leg ready
   BUY PE leg ready
   ```

3. **Entry checks:**
   ```
   [SELL_ENTRY_CHECK] ref=X, ltp=Y, decay=Z, condition_met=True/False
   ```

4. **Order placement:**
   ```
   Placing order: SELL token=X qty=Y price=Z
   Order successful
   ```

---

## 🎯 Success Criteria

Your system should show:
```
09:15:50 - PHASE0 starts
09:15:55 - PHASE0 complete (sell strikes locked)
09:16:15 - PHASE1 starts  
09:16:40 - PHASE1 complete (buy strikes locked)
09:16:46 - Entry delay complete
09:16:47 - SELL CE entry condition met → Order placed → Success
09:16:48 - SELL PE entry condition met → Order placed → Success
09:17:05 - BUY CE entry condition met → Order placed → Success
09:17:06 - BUY PE entry condition met → Order placed → Success
```

---

## 📞 Still Stuck?

If after all this, trades still don't execute:

1. **Run diagnostic and share output:**
   ```bash
   python diagnose_trade_entry.py > debug.txt
   ```

2. **Share relevant logs:**
   - Phase 0 execution (09:15-09:16)
   - Phase 1 execution (09:16-09:17)
   - Entry checks (09:17+)
   - Any error messages

3. **Share state file:**
   ```bash
   cat strategy_state.json
   ```

4. **Share config values:**
   - SELL_DECAY_TRIGGER
   - SELL_ENTRY_DELAY
   - Phase timings
   - Kill switch values

---

## ✅ Prevention Checklist

Before going live, verify:

- [ ] Run `python diagnose_trade_entry.py`
- [ ] No critical issues
- [ ] DEBUG_MODE=true for first run
- [ ] Kill switches = false
- [ ] Phase windows reasonable
- [ ] Entry triggers reasonable
- [ ] WebSocket connects successfully
- [ ] Tokens subscribe successfully
- [ ] LTP data flows
- [ ] State file writable
- [ ] Broker credentials valid
- [ ] Sufficient margin

---

**Remember:** The system is designed to be conservative. If conditions aren't met, it WON'T trade. This is by design to protect capital. Adjust parameters carefully based on backtesting and market conditions.
