LIVENESS LAYER — QUICK START GUIDE
===================================

## 5-MINUTE SETUP

### Option 1: Enable with Defaults (Console Logs Only)
```bash
export ENABLE_LIVENESS_MONITOR="true"
python main.py
```

**Expected Output:**
```
[LIVENESS] Monitor loop started
[LIVENESS] OK — 09:14:52 | NIFTY=24650.00 | Success=1 Error=0
[LIVENESS] OK — 09:15:52 | NIFTY=24651.50 | Success=2 Error=0
```

### Option 2: Enable with Custom Interval (Every 30 Seconds)
```bash
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="30"
python main.py
```

### Option 3: Enable with Telegram Notifications
```bash
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="60"
export LIVENESS_ENABLE_TELEGRAM="true"
# (Telegram notifier must be configured via TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
python main.py
```

### Option 4: Full Configuration (Pre-Market + Trading Window)
```bash
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="60"          # Check every 60s
export LIVENESS_TOKEN_SYMBOL="NIFTY"         # Monitor NIFTY spot
export LIVENESS_ENABLE_TELEGRAM="true"       # Send Telegram pings
python main.py
```

---

## VERIFICATION (While Running)

### Check Console Output
```bash
# In another terminal, tail the logs
tail -f strategy_logs/*.log | grep LIVENESS
```

### Expected Patterns

**Before Market Opens:**
```
[LIVENESS] OK — 08:45:00 | NIFTY=24625.00 | Success=1 Error=0
[LIVENESS] OK — 09:00:00 | NIFTY=24630.00 | Success=2 Error=0
```
→ System is alive before trading starts

**During Trading:**
```
[LIVENESS] OK — 09:16:05 | NIFTY=24635.00 | Success=5 Error=0
[TRADING] Entered SHORT CE: NIFTY2405124600CE @ 45.50
[LIVENESS] OK — 09:17:05 | NIFTY=24636.50 | Success=6 Error=0
```
→ System proves connectivity during trading (independent)

**During Long Delays (Phase 0/1):**
```
[LIVENESS] OK — 10:05:00 | NIFTY=24640.00 | Success=10 Error=0
[LIVENESS] OK — 10:06:00 | NIFTY=24641.00 | Success=11 Error=0
[LIVENESS] OK — 10:07:00 | NIFTY=24642.00 | Success=12 Error=0
```
→ Proves engine is working during strategy delays

---

## PROGRAMMATIC ACCESS

### Get Health Status in Code
```python
from liveness_layer import create_liveness_monitor

monitor = create_liveness_monitor(feed, notifier)

# Check current status
status = monitor.get_status()
print(f"Last LTP: {status['last_ltp']}")
print(f"Success Rate: {status['success_rate']:.1%}")
print(f"Total Checks: {status['total_checks']}")

# Quick health check (within last 120 seconds)
if monitor.is_healthy(recent_seconds=120):
    print("Liveness OK")
else:
    print("Liveness Check Failed")
```

### Manual Start/Stop
```python
from liveness_layer import LivenessMonitor

monitor = LivenessMonitor(
    feed=feed,
    notifier=notifier,
    interval_seconds=60,
    token_symbol="NIFTY",
    enable_telegram=True
)

monitor.start()   # Start monitoring
# ... do work ...
monitor.stop()    # Stop gracefully (5s timeout)
```

---

## TESTING SCENARIOS

### Scenario 1: Pre-Market Test (Before 9:15 AM)
```bash
# Run with PAPER mode before market opens
export DATA_MODE="LIVE"
export TRADING_MODE="PAPER"
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="10"   # Check every 10 seconds for faster demo
python main.py
```

**What You'll See:**
- System connects to feed
- Liveness checks run every 10 seconds
- `[LIVENESS] OK` printed even though no trades active
- This proves connectivity before market opens

### Scenario 2: Connectivity Failure Recovery
```bash
# Run with TELEGRAM enabled to see error notifications
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="20"   # Faster for testing
export LIVENESS_ENABLE_TELEGRAM="true"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat"
python main.py
```

**Simulate network issue:**
1. Let liveness run for 1-2 checks (OK)
2. Disconnect network briefly (timeout happens)
3. Reconnect network
4. Observe:
   - `[LIVENESS] ERROR` messages during disconnection
   - `[LIVENESS] OK` resumes when network back
   - Telegram notifications sent for both error and recovery
   - **Trading engine continues working** (if it had orders)

### Scenario 3: Long Phase Delay Monitoring
```bash
# Run normal live trading
export DATA_MODE="LIVE"
export TRADING_MODE="LIVE"
export ENABLE_LIVENESS_MONITOR="true"
export LIVENESS_CHECK_INTERVAL="30"
python main.py
```

**What You'll See:**
- Engine waits for Phase 0/1 data (normal behavior)
- Liveness continues printing `OK` every 30 seconds
- This proves: "System is working, just waiting for data"
- **No confusion about whether engine is frozen**

---

## DISABLE LIVENESS

### Quick Disable
```bash
# Option 1: Don't set the env var
python main.py
# (ENABLE_LIVENESS_MONITOR defaults to false)

# Option 2: Explicitly disable
export ENABLE_LIVENESS_MONITOR="false"
python main.py
```

**Expected Output:**
```
 Liveness monitor is DISABLED
```

---

## MONITORING IN PRODUCTION

### Recommended Configuration
```bash
# Clear/early morning validation (pre-market)
ENABLE_LIVENESS_MONITOR=true \
LIVENESS_CHECK_INTERVAL=60 \
LIVENESS_TOKEN_SYMBOL="NIFTY" \
LIVENESS_ENABLE_TELEGRAM=true \
python main.py
```

### Log Rotation
```bash
# The liveness logs are in strategy_logs/*.log
# Existing rotation applies (no special setup needed)
tail -f strategy_logs/strategy_*.log | grep LIVENESS
```

### Health Check Integration
```bash
# Check if liveness is working
grep -c "LIVENESS.*OK" strategy_logs/strategy_*.log | grep -v ":0"
# Output: shows number of successful checks

# Check for recent errors
grep "LIVENESS.*ERROR" strategy_logs/strategy_*.log | tail -5
```

---

## TROUBLESHOOTING

### No Liveness Output
```
Problem: [LIVENESS] messages not appearing
Solution: 
1. Check ENABLE_LIVENESS_MONITOR=true
2. Wait 60 seconds (default interval)
3. Check logs: tail -f strategy_logs/strategy_*.log | grep LIVENESS
```

### All Checks Failing
```
Problem: [LIVENESS] ERROR — repeatedly
Solution:
1. Check if feed is connected: grep "WebSocket connected" strategy_logs/*.log
2. Check if NIFTY is subscribed
3. Check if get_ltp works in independent test
4. For PAPER mode: may need LIVE data (feed.get_ltp requires LIVE)
```

### Telegram Not Sending
```
Problem: LIVENESS_ENABLE_TELEGRAM=true but no messages
Solution:
1. Verify TELEGRAM_BOT_TOKEN is set
2. Verify TELEGRAM_CHAT_ID is set
3. Check that main notifier works (other trade notifications sending?)
4. Telegram is OPTIONAL — liveness works without it
```

---

## INTEGRATION WITH MONITORING SYSTEMS

### CloudWatch / DataDog Integration
```bash
# Parse logs for metrics
grep "LIVENESS.*OK" strategy_logs/strategy_*.log | awk '{print $2}' | sort | uniq -c
# Output: count of checks per hour

grep "LIVENESS.*ERROR" strategy_logs/strategy_*.log | wc -l
# Output: total number of errors
```

### Webhook Alert (Custom)
```bash
# After each trading session, check liveness health
status=$(grep "LIVENESS" strategy_logs/strategy_*.log | tail -1)
if [[ $status == *"ERROR"* ]]; then
    curl -X POST https://your-webhook.com/alert \
        -d "Liveness check failed: $status"
fi
```

---

## SUMMARY

**Three Simple Levels:**

1. **Basic** (Console only):
   ```bash
   ENABLE_LIVENESS_MONITOR=true python main.py
   ```

2. **With Telegram**:
   ```bash
   ENABLE_LIVENESS_MONITOR=true \
   LIVENESS_ENABLE_TELEGRAM=true python main.py
   ```

3. **Aggressive Monitoring** (Every 20s):
   ```bash
   ENABLE_LIVENESS_MONITOR=true \
   LIVENESS_CHECK_INTERVAL=20 \
   LIVENESS_ENABLE_TELEGRAM=true \
   python main.py
   ```

---

**Key Points:**
- ✅ Liveness proves engine is alive before market opens
- ✅ Independent of trading logic (zero impact)
- ✅ Console logs provide real-time proof
- ✅ Optional Telegram notifications
- ✅ Fully configurable via environment variables
- ✅ Non-blocking, daemon thread, safe to enable

Generated: 2026-02-15
