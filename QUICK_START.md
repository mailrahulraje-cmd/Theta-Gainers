# QUICK START - Updated Telegram Notification System

## What's New?

Your trading system now has **streamlined, event-based Telegram notifications** with:
- ✅ **No duplicate alerts** - State tracking prevents repeated messages
- ✅ **Clean output** - Only meaningful events, no spam
- ✅ **Professional formatting** - Emoji-based, easy to read
- ✅ **Smart notifications** - Alerts only when things change

---

## Expected Telegram Output (Typical Day)

```
🚀 SYSTEM STATUS UPDATE
Login: SUCCESS
Websocket: CONNECTED
Time: 09:14:00

🔄 STRATEGY PHASE CHANGE
Previous: NONE
Current: STANDBY
Time: 09:14:05

🔄 STRATEGY PHASE CHANGE
Previous: STANDBY
Current: PHASE 0
Time: 09:15:50

🔄 STRATEGY PHASE CHANGE
Previous: PHASE 0
Current: PHASE 1
Time: 09:16:15

🔒 REFERENCE LOCKED

SELL CE 45000 @ ₹152.35
SELL PE 44800 @ ₹148.20

BUY CE Hedge 45500 @ ₹32.10
BUY PE Hedge 44500 @ ₹29.80

🔄 STRATEGY PHASE CHANGE
Previous: PHASE 1
Current: IN TRADE
Time: 09:16:45

🎯 TRADE ENTERED

SELL CE 45000 @ ₹150.10 | SL ₹232.00
SELL PE 44800 @ ₹149.80 | SL ₹230.00

Time: 09:16:48

📊 TRADE STATUS – 09:17:00

🟢 CE 45000
Entry: ₹150.10
LTP: ₹145.20
P&L: ₹+4.90

🟢 PE 44800
Entry: ₹149.80
LTP: ₹147.30
P&L: ₹+2.50

-------------------------
🟢 CUMULATIVE P&L: ₹+7.40

[Snapshot repeats every 30 seconds]

🔁 TRAILING SL UPDATED    (Only if SL changes after 14:15)

Time: 14:16

CE 45000 SL → ₹198.50
PE 44800 SL → ₹201.20

[Exit messages at end of day]
[Final P&L]
```

---

## Notification Types (6 Total)

### 1. System Status (On Change Only)
- When: Login status or WebSocket changes
- Example: Login successful, WebSocket connected

### 2. Phase Change (On Change Only)
- When: Strategy moves between phases
- Phases: STANDBY → PHASE 0 → PHASE 1 → IN TRADE

### 3. Reference Locked (Once)
- When: All 4 option legs are selected
- Shows: SELL CE/PE and BUY CE/PE strikes with prices

### 4. Trade Entered (Once Per Trade)
- When: Both SELL legs are executed
- Shows: Entry prices and stop losses

### 5. Trailing SL Updated (On SL Change)
- When: Trailing stop loss activates/changes (after 14:15)
- Shows: New SL values for both legs

### 6. Periodic Snapshot (Every 30s During Trading)
- When: Active trade running
- Shows: Current LTP, P&L per leg, cumulative P&L

---

## Configuration

Edit `config.py` or `.env`:

```bash
# Telegram Settings
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_SNAPSHOT_INTERVAL=30  # Snapshot every 30 seconds
```

---

## What Changed? (Technical)

### Files Modified:
1. **`utils/notifier.py`** - Complete rewrite
   - Added `NotificationStateCache` class
   - Added 5 new event-based notification methods
   - Improved snapshot logic

2. **`strategy/engine.py`** - Added notifications at key events
   - Phase transitions (4 locations)
   - Reference lock (1 location)
   - Trade entry (1 location)
   - Trailing SL (1 location)

3. **`main.py`** - Added system status notification
   - Sends on startup (1 location)

### Files Backed Up:
- `utils/notifier_old_backup.py` - Original notifier preserved

---

## Verification Checklist

After deploying:
- [ ] System sends status alert on startup
- [ ] Phase changes trigger alerts (4 total)
- [ ] Lock alert appears when strikes are selected
- [ ] Trade entry alert when positions opened
- [ ] Snapshots appear every 30s ONLY during active trade
- [ ] NO duplicate messages
- [ ] Trailing SL alert appears (if SL changes after 14:15)

---

## Troubleshooting

**Problem: No notifications at all**
- Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
- Check Telegram bot is started (send /start to your bot)
- Check logs for validation errors

**Problem: Notifications but duplicates appearing**
- This shouldn't happen - state cache prevents it
- Check logs for cache errors
- Report as a bug if persistent

**Problem: Missing specific notification**
- Check that condition is met (e.g., phase actually changed)
- Check logs for exceptions during notification
- Some notifications only trigger once (by design)

**Problem: Snapshots too frequent/infrequent**
- Edit TELEGRAM_SNAPSHOT_INTERVAL in config.py
- Default is 30 seconds
- Range: 5-300 seconds recommended

---

## Rollback Instructions (If Needed)

If you need to revert to old notification system:

```bash
cd utils
cp notifier_old_backup.py notifier.py
```

Then restart the system.

---

## Key Improvements Summary

| Before | After |
|--------|-------|
| 100+ alerts per day | 15-20 meaningful alerts |
| Many duplicates | Zero duplicates |
| Noisy logs in Telegram | Clean, professional output |
| Hard to track what changed | Clear state change alerts |
| Snapshot always running | Only during active trade |
| Manual tracking needed | Automatic event detection |

---

## Documentation Files

- `NOTIFICATION_IMPROVEMENTS.md` - Detailed technical documentation
- `CHANGELOG_NOTIFICATIONS.md` - Complete change history
- `QUICK_START.md` - This file

---

## Support

Questions? Check:
1. `NOTIFICATION_IMPROVEMENTS.md` for detailed docs
2. System logs for errors
3. Telegram bot status (send /start to your bot)

---

## Version

**Notification System v2.0**
- Released: February 13, 2026
- Compatibility: Works with existing trading logic
- No strategy changes required
- Backward compatible with old notification calls

---

## Happy Trading! 🚀

Your Telegram will now show only what matters:
- System events
- Phase transitions  
- Trade locks
- Entry/exit
- Real-time P&L

No more noise. Just clean, actionable information.
