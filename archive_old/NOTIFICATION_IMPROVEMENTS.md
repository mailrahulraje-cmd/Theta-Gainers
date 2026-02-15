# Trading System - Telegram Notification Improvements

## Overview
This document describes the streamlined Telegram notification system that implements clean, event-based alerts with no duplicates.

## Implementation Summary

### 1. New Notifier Module (`utils/notifier.py`)

**Key Features:**
- **State-change tracking**: `NotificationStateCache` class prevents duplicate notifications
- **Event-based alerts**: Notifications only sent when values actually change
- **Clean message format**: Professional, emoji-based formatting
- **Periodic snapshots**: Config-controlled interval, only during IN_TRADE phase
- **Thread-safe**: All operations protected with locks

### 2. Notification Types Implemented

#### A. System Status Alerts (Event-Based)
```python
notifier.send_system_status(login_status, websocket_status)
```
- Triggers: State change only
- Format:
```
🚀 SYSTEM STATUS UPDATE

Login: SUCCESS
Websocket: CONNECTED
Time: 09:15:03
```

#### B. Phase Change Alerts (Event-Based)
```python
notifier.send_phase_change(new_phase)
```
- Triggers: Phase transition only
- Phases: "STANDBY", "PHASE 0", "PHASE 1", "IN TRADE", "EXITED"
- Format:
```
🔄 STRATEGY PHASE CHANGE

Previous: PHASE 0
Current: PHASE 1
Time: 09:20:01
```

#### C. Lock Event Alert (Once Per Lock)
```python
notifier.send_lock_event(
    sell_ce_strike, sell_ce_price,
    sell_pe_strike, sell_pe_price,
    buy_ce_strike, buy_ce_price,
    buy_pe_strike, buy_pe_price
)
```
- Triggers: When all 4 legs (SELL CE, SELL PE, BUY CE, BUY PE) are locked
- Format:
```
🔒 REFERENCE LOCKED

SELL CE 45000 @ ₹152.35
SELL PE 44800 @ ₹148.20

BUY CE Hedge 45500 @ ₹32.10
BUY PE Hedge 44500 @ ₹29.80
```

#### D. Trade Entry Alert (Once Per Trade)
```python
notifier.send_trade_entry(
    sell_ce_strike, sell_ce_price, sell_ce_sl,
    sell_pe_strike, sell_pe_price, sell_pe_sl
)
```
- Triggers: When both SELL legs are entered
- Format:
```
🎯 TRADE ENTERED

SELL CE 45000 @ ₹150.10 | SL ₹232.00
SELL PE 44800 @ ₹149.80 | SL ₹230.00

Time: 09:20:05
```

#### E. Trailing SL Update Alert (On SL Change Only)
```python
notifier.send_trailing_sl_update(ce_strike, ce_sl, pe_strike, pe_sl)
```
- Triggers: Only when SL value changes (after 14:15 when trailing activates)
- Format:
```
🔁 TRAILING SL UPDATED

Time: 14:01

CE 45000 SL → ₹198.50
PE 44800 SL → ₹201.20
```

#### F. Periodic Snapshot (Config-Controlled Interval)
- Triggers: Every `TELEGRAM_SNAPSHOT_INTERVAL` seconds (from config.py)
- Only sent when phase = "IN TRADE"
- Format:
```
📊 TRADE STATUS – 14:05

🟢 CE 45000
Entry: ₹150.10
LTP: ₹112.40
P&L: ₹+37.70

🔴 PE 44800
Entry: ₹149.80
LTP: ₹160.10
P&L: ₹-10.30

-------------------------
🟢 CUMULATIVE P&L: ₹+27.40
```

## Integration Points

### 1. Strategy Engine (`strategy/engine.py`)

**Phase Change Notifications:**
- Added in `_phase_monitor()` at each phase transition
- Locations: Lines ~312, ~324, ~335, ~348

**Lock Event Notification:**
- Added in `_execute_phase1()` when all 4 legs are locked
- Location: Line ~575

**Trade Entry Notification:**
- Added in `_entry_monitor()` when both SELL legs are entered
- Location: Line ~620

**Trailing SL Notification:**
- Added in `_check_sell_exit()` when trailing SL activates
- Location: Line ~920

### 2. Main Entry Point (`main.py`)

**System Status Notification:**
- Added after login and component initialization
- Location: Line ~243

## State Cache Mechanism

The `NotificationStateCache` class maintains in-memory state to prevent duplicates:

```python
class NotificationStateCache:
    - last_login_status
    - last_websocket_status
    - last_phase
    - last_lock_reference
    - trade_entry_sent
    - last_sl_ce
    - last_sl_pe
```

Each notification method checks the cache before sending:
```python
if new_value != last_sent_value:
    send_alert()
    update_last_sent_value
```

## Configuration

All notification settings are in `config.py`:

```python
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_SNAPSHOT_INTERVAL = int(os.getenv("TELEGRAM_SNAPSHOT_INTERVAL", "30"))
```

## Backward Compatibility

The improved notifier maintains backward compatibility with legacy methods:
- `send_entry()` - Still works, adds to leg tracking
- `send_exit()` - Still works, removes from leg tracking
- `heartbeat()` - Still works, updates internal state
- `send_trade_log()` - Still works for important logs
- `send_ws_status()` - Maps to `send_system_status()`

## Expected Telegram Output During Trading Day

```
🚀 SYSTEM STATUS UPDATE
Login: SUCCESS
Websocket: CONNECTED

🔄 STRATEGY PHASE CHANGE
Previous: STANDBY
Current: PHASE 0

🔄 STRATEGY PHASE CHANGE
Previous: PHASE 0
Current: PHASE 1

🔒 REFERENCE LOCKED
SELL CE 45000 @ ₹152.35
SELL PE 44800 @ ₹148.20
BUY CE Hedge 45500 @ ₹32.10
BUY PE Hedge 44500 @ ₹29.80

🔄 STRATEGY PHASE CHANGE
Previous: PHASE 1
Current: IN TRADE

🎯 TRADE ENTERED
SELL CE 45000 @ ₹150.10 | SL ₹232.00
SELL PE 44800 @ ₹149.80 | SL ₹230.00

[Periodic snapshots every 30s showing P&L]

🔁 TRAILING SL UPDATED (at 14:15+ if trailing activates)
CE 45000 SL → ₹198.50
PE 44800 SL → ₹201.20

[Exit messages]

[Final P&L]
```

## Key Improvements

1. **No Duplicate Alerts**: State cache prevents sending same message multiple times
2. **Clean Output**: Professional formatting with appropriate emojis
3. **Event-Driven**: Notifications only on state changes
4. **Minimal Noise**: No debug logs, no internal variables exposed
5. **Config-Controlled**: Snapshot interval from config, easy to adjust
6. **Thread-Safe**: All operations protected with locks
7. **Backward Compatible**: Existing code still works

## Files Modified

1. `utils/notifier.py` - Complete rewrite with state-change tracking
2. `strategy/engine.py` - Added notification calls at key events
3. `main.py` - Added system status notification

## Files Backed Up

- `utils/notifier_old_backup.py` - Original notifier preserved

## Testing Recommendations

1. Start system and verify system status alert
2. Watch for phase change alerts during market open
3. Verify lock event alert when all 4 legs are selected
4. Verify trade entry alert when sell legs are executed
5. Monitor periodic snapshots (should appear every 30s during IN_TRADE only)
6. After 14:15, verify trailing SL alert if SL is modified
7. Confirm NO duplicate messages at any point

## Troubleshooting

**No notifications received:**
- Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
- Check notifier validation logs

**Duplicate notifications:**
- Check state cache is working (should be automatic)
- Check logs for errors in cache operations

**Missing notifications:**
- Check that appropriate conditions are met
- Check logs for exceptions in notification calls

**Snapshots too frequent/infrequent:**
- Adjust TELEGRAM_SNAPSHOT_INTERVAL in config.py or .env
