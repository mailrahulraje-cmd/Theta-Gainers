# Notification Implementation Guide

**Date:** February 15, 2026  
**Status:** Implementation Complete  
**Scope:** Telegram notification categorization and one-time/periodic alert system

---

## Overview

This document describes the complete implementation of the notification categorization system outlined in [NOTIFICATION_PLAN.md](NOTIFICATION_PLAN.md). All enhancements are backward-compatible with existing code.

---

## Implementation Summary

### ✅ Completed Components

#### 1. **NotificationStateCache Enhancements** (Deduplication Layer)

**File:** `utils/notifier.py` - Class `NotificationStateCache`

**New Methods:**
```python
# Error rate-limiting (max 1 per type per 10 seconds)
should_send_error(error_type: str) -> bool

# Connection status tracking
should_send_connection_event(status: str) -> bool

# P&L milestone tracking (one-time per milestone per session)
should_send_pnl_milestone(milestone: str) -> bool
```

**Behavior:**
- Each error type is independently rate-limited
- Connection lost/restored each occur once before toggling again
- P&L milestones ("100_PERCENT", "150_PERCENT", "MAX_LOSS") are tracked per session

---

#### 2. **Error Alert Methods** (NEW - Categorized)

**File:** `utils/notifier.py` - Class `TelegramNotifierTextOnly`

**Connection Errors** (ONE-TIME per occurrence):
```python
def send_connection_lost(service: str, last_ltp_time: str = None, retry_info: str = None)
```
- Triggers: WebSocket disconnect, API timeout, connection lost
- Recovery: Call `send_connection_restored(service)` to alert reconnection
- Format: Clean error message with last LTP timestamp and retry status

**Trade Errors** (Rate-limited to 1 per 10 sec):
```python
def send_trade_error(leg: str, strike: int, qty: int, reason: str)
```
- Triggers: Order rejection, insufficient margin, exchange circuit breaker
- Deduplication: Max 1 alert per 10 seconds across all trade errors
- Format: Leg details + specific error reason + action required

**Data Errors** (Rate-limited to 1 per 10 sec):
```python
def send_data_error(issue: str, token: str = None, status: str = None)
```
- Triggers: Missing LTP after grace period, invalid strike, schema violation
- Deduplication: Max 1 alert per 10 seconds across all data errors
- Format: Issue description + token + current status + recommendation

---

#### 3. **P&L Milestone Alerts** (NEW - One-Time)

**File:** `utils/notifier.py` - Class `TelegramNotifierTextOnly`

```python
def send_pnl_milestone(milestone_type: str, current_pnl: float, 
                      daily_target: float = None, cumulative_pnl: float = None)
```

**Milestone Types:**
- `"100_PERCENT"` - Daily target achieved (first alert)
- `"150_PERCENT"` - 150% of daily target (second alert)
- `"MAX_LOSS"` - Max daily loss triggered (critical alert)

**Behavior:**
- Each milestone is sent ONCE per trading session
- Milestones are tracked in `NotificationStateCache.pnl_milestones_sent` set
- Set is reset daily (clear when market opens)

**Integration Points:**
- Call in engine.py P&L monitoring when thresholds are crossed
- Pass cumulative P&L to show both daily and YTD performance

---

#### 4. **System Startup Alert** (ENHANCED)

**File:** `utils/notifier.py` - Class `TelegramNotifierTextOnly`

```python
def send_system_startup(trading_mode: str, broker_name: str, 
                       instruments_count: int, status: str = "CONNECTED")
```

**Current Implementation:**
- Calls automatically in `start()` method with basic message
- Can be overridden with enhanced call in main.py initialization

**To Use Enhanced Startup:**
```python
# In main.py after notifier initialization:
if notifier:
    notifier.send_system_startup(
        trading_mode=Config.TRADING_MODE,
        broker_name="Angel One",
        instruments_count=len(instruments.data),
        status="READY"
    )
```

**Format:** Mode emoji + broker info + instruments loaded + status

---

#### 5. **Daily Heartbeat Alert** (NEW - Periodic)

**File:** `utils/notifier.py` - Class `TelegramNotifierTextOnly`

```python
def send_daily_heartbeat(trades_count: int, daily_pnl: float, win_rate: float,
                        cumulative_pnl: float = None, session_start_time: str = None)
```

**Typical Usage (at 15:45 IST):**
```python
# In main.py or a scheduled task:
notifier.send_daily_heartbeat(
    trades_count=3,
    daily_pnl=5200.0,
    win_rate=75.0,
    cumulative_pnl=48500.0,
    session_start_time="09:30"
)
```

**Behavior:**
- Typically sent once per day at market close (default: 15:45 IST)
- Auto-selects emoji based on P&L (profit/loss/break-even)
- NOT rate-limited or deduplicated (should be called once per day manually)

**Config-Controlled Settings:**
```python
# In config.py:
HEARTBEAT_ENABLED = True
HEARTBEAT_TIME = "15:45"  # IST
```

---

### 🔧 Configuration Options Added

**File:** `config.py`

```python
# NOTIFICATION ALERT FLAGS
NOTIFY_STARTUP = True                      # System startup confirmation
NOTIFY_ERRORS = True                       # Connection/trade/data errors
NOTIFY_ENTRIES = True                      # Trade entries (already existed)
NOTIFY_EXITS = True                        # Trade exits (already existed)
NOTIFY_SL_CHANGES = True                   # Trailing SL updates (already existed)
NOTIFY_PNL_MILESTONES = True              # P&L milestone alerts
NOTIFY_CONNECTION_EVENTS = True            # Connection lost/restored

# P&L MILESTONE THRESHOLDS
PNL_MILESTONE_100_PERCENT = True           # Send at 100% of daily target
PNL_MILESTONE_150_PERCENT = True           # Send at 150% of daily target
PNL_MAX_DAILY_LOSS_PERCENT = 50.0         # Default: 50% of capital allocation

# PERIODIC SNAPSHOT SETTINGS
SNAPSHOT_ONLY_IN_TRADE = True             # Only snapshot during IN_TRADE phase
SNAPSHOT_PNL_THRESHOLD = 10.0             # Rupees - skip if P&L change < threshold

# DAILY HEARTBEAT SETTINGS
HEARTBEAT_ENABLED = True
HEARTBEAT_TIME = "15:45"                  # IST, HH:MM format

# ERROR DEDUPLICATION
ERROR_RATE_LIMIT_SECONDS = 10             # Max 1 error alert per 10 sec per type
```

---

## Alert Flow Diagrams

### System Startup Flow
```
Application Start
    ↓
create_broker() → Create broker instance
    ↓
TelegramNotifierTextOnly.start()
    ├─ Validate credentials
    ├─ Send "SYSTEM STARTUP" alert (basic: in start())
    └─ Start snapshot daemon thread
    ↓
Optional: send_system_startup(enhanced)
    └─ Enhanced startup with mode/broker/instruments
```

### Error Alert Flow
```
Error Occurs (e.g., order rejection)
    ↓
engine.py / broker.py detects error
    ↓
Call notifier.send_trade_error(leg, strike, qty, reason)
    ↓
NotificationStateCache.should_send_error("TRADE")?
    ├─ YES: Enough time elapsed since last TRADE error
    │   → Send alert + log error
    │   → Update last_error_time["TRADE"]
    │
    └─ NO: Recent TRADE error already sent
        → Skip (suppressed) + debug log
```

### P&L Milestone Flow
```
Continuous P&L Monitoring
    ↓  (each tick or periodic check)
Calculate current_pnl vs daily_target
    ↓
Is current_pnl >= 100% of daily_target?
├─ YES: Call send_pnl_milestone("100_PERCENT", ...)
│       → NotificationStateCache checks if already sent
│       ├─ NO: Send alert, add to pnl_milestones_sent
│       └─ YES: Skip (already sent this session)
│
└─ NO: Continue monitoring
```

### Daily Heartbeat Flow
```
Market Close (typically 15:45 IST)
    ↓
Defer to separate heartbeat task/scheduler
    ↓
Collect session statistics:
  - trades_count: Count completed trades
  - daily_pnl: Today's net P&L
  - win_rate: Wins/(Wins+Losses) * 100
  - cumulative_pnl: YTD P&L
    ↓
Call notifier.send_daily_heartbeat(...)
    ↓
Send formatted message (not rate-limited)
```

---

## Integration Points

### In main.py

After notifier initialization:
```python
# Optional: Send enhanced startup alert
if notifier and Config.NOTIFY_STARTUP:
    try:
        instruments_count = len(instruments.data) if instruments else 0
        notifier.send_system_startup(
            trading_mode=Config.TRADING_MODE,
            broker_name="Angel One",
            instruments_count=instruments_count,
            status="READY"
        )
    except Exception as e:
        logger.warning(f"Failed to send enhanced startup: {e}")
```

### In strategy/engine.py

When errors occur:
```python
# Connection error example
try:
    self.feed.subscribe(tokens)
except Exception as e:
    if self.notifier:
        self.notifier.send_connection_lost(
            service="WebSocket",
            last_ltp_time=self._last_tick_time,
            retry_info="Auto-reconnecting (attempt 2/5)..."
        )
    # Continue with reconnection logic

# Trade error example
except OrderException as e:
    if self.notifier:
        self.notifier.send_trade_error(
            leg="BUY CE",
            strike=22000,
            qty=15,
            reason=f"Order rejected: {e.message}"
        )

# P&L milestone check
current_pnl = self.trade_leg_manager.get_cumulative_pnl()
daily_target = Config.DAILY_PNL_TARGET
if current_pnl >= daily_target and self.notifier:
    self.notifier.send_pnl_milestone(
        milestone_type="100_PERCENT",
        current_pnl=current_pnl,
        daily_target=daily_target,
        cumulative_pnl=self.cumulative_pnl
    )
```

### Scheduled Task (via external scheduler or cron)

For daily heartbeat:
```python
# Run at 15:45 IST daily
import subprocess

result = subprocess.run([
    "python", "-c",
    """
from main import get_session_stats
from utils.notifier import TelegramNotifierTextOnly
from config import Config

stats = get_session_stats()
notifier = TelegramNotifierTextOnly(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
notifier.send_daily_heartbeat(
    trades_count=stats['trades'],
    daily_pnl=stats['pnl'],
    win_rate=stats['win_rate'],
    cumulative_pnl=stats['cumulative']
)
"""
], capture_output=True)
```

---

## Backward Compatibility

All changes are **100% backward compatible**:

1. ✅ **No function signature changes** - All new methods are additions only
2. ✅ **No trading logic changes** - Pure notification layer enhancements
3. ✅ **Legacy methods preserved** - `send_entry()`, `send_exit()`, `send_trade_log()` still work
4. ✅ **Optional config** - All new settings have defaults; can be disabled
5. ✅ **Lock-free for trading** - Two-stage pattern unchanged; snapshot daemon still non-blocking

---

## Testing Checklist

### Unit Testing
- [ ] Test `NotificationStateCache.should_send_error()` with multiple error types
- [ ] Test `should_send_connection_event()` - verify state transitions (LOST → RESTORED)
- [ ] Test `should_send_pnl_milestone()` - verify one-time send per session
- [ ] Test snapshot deduplication (skip if P&L < SNAPSHOT_PNL_THRESHOLD)

### Integration Testing
- [ ] Call `send_connection_lost()` → verify Telegram alert sent
- [ ] Call `send_trade_error()` twice in quick succession → verify only first sent
- [ ] Call `send_pnl_milestone()` twice for same milestone → verify only first sent
- [ ] Call `send_daily_heartbeat()` → verify session summary format

### End-to-End Testing (Paper Mode)
- [ ] Disable Telegram for initial testing (set BOT_TOKEN="")
- [ ] Run trading system, verify alerts logged (not sent)
- [ ] Enable Telegram with test chat, run again
- [ ] Verify alerts arrive in Telegram with proper formatting

---

## Known Limitations & Future Enhancements

### Current Limitations
1. **Daily Heartbeat:** Manual call required (not auto-scheduled; requires external scheduler)
2. **P&L Milestones:** Requires manual integration in engine.py (not auto-triggered yet)
3. **Emojis:** Simple placeholder emojis; can be enhanced
4. **Greek Updates:** Not yet implemented (Phase 3 feature)

### Recommended Next Steps (Phase 2)
1. [ ] Add daily heartbeat scheduler task
2. [ ] Auto-trigger P&L milestone checks in engine loop
3. [ ] Add multi-leg entry alert (consolidated brief format)
4. [ ] Implement Greek updates during IN_TRADE

### Advanced Features (Phase 3)
1. [ ] Mobile command handler (e.g., "Show balance", "Close position X")
2. [ ] Recommendation engine ("Close now?" based on P&L/time-decay)
3. [ ] Intra-trade Greek monitoring (IV changes, delta shifts)

---

## Summary of Changes

| Component | Type | Status | Notes |
|-----------|------|--------|-------|
| **NotificationStateCache** | Enhancement | ✅ Complete | Added error/connection/milestone dedup |
| **Error Alerts** | New Methods | ✅ Complete | 3 new methods: connection/trade/data |
| **P&L Milestones** | New Method | ✅ Complete | 1 new method for milestone tracking |
| **System Startup** | Enhancement | ✅ Complete | Enhanced method added to existing flow |
| **Daily Heartbeat** | New Method | ✅ Complete | 1 new method for session summary |
| **Config Settings** | Addition | ✅ Complete | 13 new config options added |
| **Snapshot Enhancement** | Minor | ✅ Complete | Non-blocking pattern preserved |

---

## Testing the Implementation

### Quick Test Script

```python
# test_notifications.py
from utils.notifier import TelegramNotifierTextOnly
from config import Config
import time

# Initialize notifier
notifier = TelegramNotifierTextOnly(
    Config.TELEGRAM_BOT_TOKEN,
    Config.TELEGRAM_CHAT_ID,
    interval=Config.TELEGRAM_SNAPSHOT_INTERVAL
)
notifier.start()

# Test 1: System startup
print("Test 1: System startup...")
notifier.send_system_startup(
    trading_mode="PAPER",
    broker_name="Angel One",
    instruments_count=42,
    status="READY"
)
time.sleep(2)

# Test 2: Error alerts (rate-limited)
print("Test 2: Trade errors (should suppress second)...")
notifier.send_trade_error("BUY CE", 22000, 15, "Insufficient margin")
time.sleep(0.5)
notifier.send_trade_error("SELL PE", 22000, 15, "Another error")  # Suppressed
time.sleep(2)

# Test 3: Connection events
print("Test 3: Connection events...")
notifier.send_connection_lost("WebSocket", "09:45:30")
time.sleep(2)
notifier.send_connection_restored("WebSocket")
time.sleep(2)

# Test 4: P&L milestones
print("Test 4: P&L milestones (one-time each)...")
notifier.send_pnl_milestone("100_PERCENT", 5000.0, 5000.0, 45000.0)
time.sleep(2)
notifier.send_pnl_milestone("150_PERCENT", 7500.0, 5000.0, 47500.0)
time.sleep(2)

# Test 5: Daily heartbeat
print("Test 5: Daily heartbeat...")
notifier.send_daily_heartbeat(
    trades_count=3,
    daily_pnl=5200.0,
    win_rate=75.0,
    cumulative_pnl=48500.0
)

notifier.stop()
print("All tests completed!")
```

---

## Support & Troubleshooting

### Alert Not Sent?
1. Check `NOTIFY_*` flag in config is True
2. Check deduplication cache - may have been suppressed
3. Verify Telegram bot token and chat ID are valid
4. Check logs for "suppressed (rate limited)" messages

### Too Many Alerts?
1. Increase `ERROR_RATE_LIMIT_SECONDS` to reduce error spam
2. Increase `SNAPSHOT_PNL_THRESHOLD` to skip minor updates
3. Disable specific alert types: set `NOTIFY_*=False` in config

### Telegram Not Responding?
1. Check network connectivity
2. Verify bot token is still valid (regenerate if needed)
3. Check logs for `Telegram gateway wrapper exception`
4. Note: Slow Telegram should NOT block trading (lock-free design)

---

**Implementation Date:** February 15, 2026  
**Last Updated:** February 15, 2026
