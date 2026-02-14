# ✅ Trade Entry Debugging - Quick Checklist

## 🚨 Run This IMMEDIATELY if Trades Don't Execute

### ⚡ Step 1: Run Diagnostic (30 seconds)
```bash
cd /path/to/trading_system
python diagnose_trade_entry.py
```

**Look for:**
- ❌ Any CRITICAL ISSUES
- ⚠️ Any WARNINGS
- Note all red ❌ items

**If you see:**
- `KILL_SWITCH_ENABLED=true` → Set to false immediately
- `NO_NEW_TRADES=true` → Set to false immediately
- `Phase 0 not completed` → Proceed to Step 2
- `SELL legs not ready` → Proceed to Step 2

---

### 🔍 Step 2: Check State File (10 seconds)
```bash
cat strategy_state.json
```

**Expected after market open:**
```json
{
  "phase0_done": true,
  "phase1_done": true,
  "sell_ce_leg_ready": true,
  "sell_pe_leg_ready": true,
  "buy_ce_leg_ready": true,
  "buy_pe_leg_ready": true,
  "sell_ce_entered": false,  // Should become true when trade enters
  "sell_pe_entered": false
}
```

**If any `_ready` is false:**
→ Go to "Phase Completion Problems" section

**If all `_ready` are true but `_entered` is false:**
→ Go to "Entry Condition Problems" section

---

### 📊 Step 3: Check Logs (2 minutes)
```bash
# Look at logs from today
tail -100 strategy_logs/strategy_*.log | grep -E "PHASE0|PHASE1|SELL_ENTRY_CHECK|Order"
```

**What to look for:**

**✅ Good signs:**
```
PHASE0: ATM=24500, CE=24400, PE=24600
PHASE1: OTM CE=24900, OTM PE=24100
[SELL_ENTRY_CHECK] CE ref=150.00, ltp=148.00, decay=2.00, trigger=2.00, condition_met=True
Placing order: SELL token=12345 qty=50 price=148.00
Order successful
```

**❌ Bad signs:**
```
PHASE0: Spot LTP unavailable
LTP unavailable for token=12345
[SELL_ENTRY_CHECK] CE ref=150.00, ltp=148.50, decay=1.50, trigger=2.00, condition_met=False
Order failed
```

---

## 🎯 Problem Categories

### A. Phase Completion Problems

**Symptoms:**
- `phase0_done: false` or `phase1_done: false`
- Legs not marked ready
- No strikes selected

**Quick Fixes:**

1. **Check time windows:**
   ```python
   # In config.py
   PHASE0_START = time(9, 15, 50)
   PHASE0_END = time(9, 16, 10)    # 20 seconds window
   PHASE1_START = time(9, 16, 15)
   PHASE1_END = time(9, 16, 45)    # 30 seconds window
   ```
   
   **Action:** If too short, extend:
   ```python
   PHASE0_END = time(9, 16, 15)    # +5 seconds
   PHASE1_END = time(9, 16, 50)    # +5 seconds
   ```

2. **Check WebSocket:**
   ```bash
   grep "WebSocket" strategy_logs/strategy_*.log | tail -5
   ```
   
   **Should see:** `WebSocket: CONNECTED` or `on_open called`
   
   **If not:** Restart system, check network

3. **Check spot LTP:**
   ```bash
   grep "Spot LTP" strategy_logs/strategy_*.log | tail -5
   ```
   
   **Should see:** `Spot LTP: 24500.50`
   
   **If not:** WebSocket not working or feed delayed

**Action Plan:**
- [ ] Restart system
- [ ] Enable DEBUG_MODE=true
- [ ] Run during market hours (9:15-9:17)
- [ ] Watch logs real-time
- [ ] Verify WebSocket connects
- [ ] Verify spot token subscribed

---

### B. Entry Condition Problems

**Symptoms:**
- Phases complete ✅
- Legs ready ✅
- But trades don't enter ❌

**Check entry conditions in logs:**
```
[SELL_ENTRY_CHECK] CE ref=150.00, ltp=148.50, decay=1.50, trigger=2.00, condition_met=False
```

**Analysis:**
- Reference: 150.00
- Current LTP: 148.50
- Decay: 1.50 (ref - ltp)
- Trigger: 2.00 (from config)
- **Problem:** 1.50 < 2.00 → Condition NOT met

**Quick Fixes:**

1. **Lower decay trigger (RECOMMENDED):**
   ```python
   # In config.py
   SELL_DECAY_TRIGGER = 1.0  # Was 2.0
   ```
   
   **Effect:** Easier to trigger, more trades

2. **Reduce entry delay:**
   ```python
   # In config.py
   SELL_ENTRY_DELAY = 0.5  # Was 1.0
   ```
   
   **Effect:** Check conditions sooner

3. **Wait for market to move:**
   - If premium is at 148.50, need it to drop to 148.00
   - This might happen naturally
   - Monitor and adjust if never triggers

**Action Plan:**
- [ ] Note current decay values from logs
- [ ] Calculate: How much more decay needed?
- [ ] Decide: Reasonable or unrealistic?
- [ ] If unrealistic: Lower SELL_DECAY_TRIGGER
- [ ] Test next trading session

---

### C. LTP Availability Problems

**Symptoms:**
```
[SELL_ENTRY_CHECK] LTP unavailable for token=12345
```

**Quick Fixes:**

1. **Check WebSocket status:**
   ```bash
   grep -i "websocket\|on_open\|on_close" strategy_logs/strategy_*.log | tail -10
   ```

2. **Check token subscription:**
   ```bash
   grep "Subscribed\|subscribe" strategy_logs/strategy_*.log | tail -10
   ```

3. **Check feed health:**
   ```bash
   grep "feed.*health\|degraded\|dead" strategy_logs/strategy_*.log | tail -10
   ```

**Action Plan:**
- [ ] Restart system if WebSocket dead
- [ ] Check network connectivity
- [ ] Verify API credentials
- [ ] Check Angel One server status
- [ ] Wait 2-3 seconds after subscription (grace period)

---

### D. Order Placement Problems

**Symptoms:**
```
[SELL_ENTRY_CHECK] ✅ CONDITION MET - Placing order
[SELL_ENTRY_CHECK] ❌ Order failed
```

**Quick Fixes:**

1. **Check broker logs:**
   ```bash
   grep -i "order.*fail\|broker.*error\|margin" strategy_logs/strategy_*.log | tail -20
   ```

2. **Check margin:**
   - Insufficient funds?
   - Check broker account

3. **Check time:**
   - Is it actually market hours?
   - Not pre-market or post-market?

4. **Check credentials:**
   ```python
   # In .env
   ANGEL_API_KEY=...
   ANGEL_CLIENT_CODE=...
   ANGEL_PASSWORD=...
   ANGEL_TOTP_SECRET=...
   ```

**Action Plan:**
- [ ] Verify sufficient margin
- [ ] Check broker account status
- [ ] Verify API credentials
- [ ] Check if API rate limited
- [ ] Try paper trading first

---

## 🔧 Quick Config Adjustments

### For More Trades (Aggressive)
```python
# In config.py
SELL_DECAY_TRIGGER = 1.0        # Was 2.0 (easier to trigger)
SELL_ENTRY_DELAY = 0.5          # Was 1.0 (faster entry)
BUY_TRIGGER_MULTIPLIER = 1.5    # Was 1.8 (easier to trigger)
```

### For Safer Trades (Conservative)
```python
# In config.py
SELL_DECAY_TRIGGER = 3.0        # Was 2.0 (harder to trigger)
SELL_ENTRY_DELAY = 2.0          # Was 1.0 (more confirmation)
BUY_TRIGGER_MULTIPLIER = 2.0    # Was 1.8 (higher bar)
```

### For Debugging
```python
# In config.py or .env
DEBUG_MODE = true               # Detailed logs
```

---

## 📝 5-Minute Debug Session

Set a timer for 5 minutes and complete:

### Minute 1: Diagnostic
```bash
python diagnose_trade_entry.py > debug.txt
cat debug.txt | grep "❌\|⚠️"
```

### Minute 2: State Check
```bash
cat strategy_state.json
```
Note: Are phases done? Are legs ready?

### Minute 3: Config Check
```bash
grep -E "KILL|DECAY|DELAY|TRIGGER" config.py
```
Note: Any obvious issues?

### Minute 4: Log Check
```bash
tail -50 strategy_logs/strategy_*.log | grep -E "ERROR|FAIL|unavailable"
```
Note: What's failing?

### Minute 5: Action Plan
Based on above, pick ONE fix:
- [ ] Disable kill switch
- [ ] Lower SELL_DECAY_TRIGGER
- [ ] Extend phase windows
- [ ] Restart system
- [ ] Fix WebSocket issue

---

## 🎯 Success Indicators

**Your logs should show:**
```
09:15:50 ✅ PHASE0 started
09:15:55 ✅ PHASE0: ATM=24500, strikes selected
09:16:15 ✅ PHASE1 started
09:16:40 ✅ PHASE1: OTM strikes selected
09:16:45 ✅ Both phases complete, legs ready
09:16:47 ✅ Entry condition met for CE
09:16:47 ✅ Order placed: SELL CE
09:16:47 ✅ Order successful
09:16:48 ✅ Entry condition met for PE
09:16:48 ✅ Order placed: SELL PE
09:16:48 ✅ Order successful
```

**Your state file should show:**
```json
{
  "phase0_done": true,
  "phase1_done": true,
  "sell_ce_entered": true,
  "sell_pe_entered": true
}
```

---

## ⚡ Emergency Quick Fix

**If completely stuck, try this:**

```bash
# Stop system
# Edit config.py

# Change these 3 lines:
SELL_DECAY_TRIGGER = 0.5      # Very easy to trigger
SELL_ENTRY_DELAY = 0.1        # Almost immediate
DEBUG_MODE = True             # See everything

# Delete state file
rm strategy_state.json

# Restart system and watch logs
tail -f strategy_logs/strategy_*.log | grep "SELL_ENTRY_CHECK"
```

**This will:**
- Make entry almost guaranteed (if legs ready and LTP available)
- Show detailed logs
- Start fresh with no old state

**Watch for:**
- Entry condition checks every 0.5s
- condition_met=True should appear quickly
- Orders should place if WebSocket working

---

## 📞 Still Not Working?

After trying all above:

1. **Share these 3 items:**
   ```bash
   # 1. Diagnostic output
   python diagnose_trade_entry.py > debug.txt
   
   # 2. State file
   cat strategy_state.json > state.txt
   
   # 3. Recent logs with entry checks
   grep "SELL_ENTRY_CHECK" strategy_logs/strategy_*.log | tail -50 > logs.txt
   ```

2. **Note these details:**
   - What time did you run system?
   - Did phases complete?
   - Did you see any entry condition checks?
   - What was the outcome of those checks?
   - Any error messages?

3. **Review:**
   - TRADE_ENTRY_DEBUGGING.md (comprehensive guide)
   - NOTIFICATION_IMPROVEMENTS.md (for alert issues)

---

## ✅ Final Checklist

Before next trading session:

- [ ] Run diagnostic script
- [ ] No kill switches enabled
- [ ] DEBUG_MODE=true for detailed logs
- [ ] Phase windows long enough (20s+ each)
- [ ] Entry triggers reasonable (SELL_DECAY_TRIGGER = 1-2)
- [ ] Entry delay short (0.5-1.0s)
- [ ] State file deleted or empty
- [ ] Sufficient margin in account
- [ ] API credentials valid
- [ ] System starts before 09:15:50

**Remember:** System is conservative by design. If it doesn't trade, there's usually a good reason. Debug systematically, don't just guess!
