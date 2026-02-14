#!/usr/bin/env python3
"""
NO TRADE DIAGNOSTIC TOOL
Analyzes why the trading system is not executing trades
"""

import sys
import os
import json
from datetime import datetime, time as dt_time

# Add system path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from constants import (
    PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1,
    PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED
)
from strategy.instruments import InstrumentMaster

print("="*80)
print("NO TRADE DIAGNOSTIC TOOL")
print("="*80)
print()

# Check 1: State File
print("CHECK 1: STATE FILE ANALYSIS")
print("-"*80)
if os.path.exists(Config.STATE_FILE):
    with open(Config.STATE_FILE, 'r') as f:
        state = json.load(f)
    
    print(f" State file exists: {Config.STATE_FILE}")
    print(f"State contents:")
    for key, value in state.items():
        print(f"  {key}: {value}")
    
    # LEGACY FORMAT DETECTION
    # Check if using flat boolean flags (legacy) vs structured leg objects (new)
    legacy_flags = [k for k in state.keys() if k.endswith('_leg_ready')]
    flat_flags = [k for k in state.keys() if k in ['sell_ce_entered', 'sell_pe_entered', 'buy_ce_entered', 'buy_pe_entered']]
    
    if flat_flags and not legacy_flags:
        print()
        print("  LEGACY STATE FORMAT DETECTED")
        print("   State file uses flat boolean flags (legacy format)")
        print("   Consider migrating to structured leg state for better resilience")
        print()
    
    # Check for blocking flags
    blocking_flags = []
    if state.get('phase1_done'):
        blocking_flags.append('phase1_done=true')
    if state.get('buy_ce_entered'):
        blocking_flags.append('buy_ce_entered=true')
    if state.get('sell_ce_entered'):
        blocking_flags.append('sell_ce_entered=true')
    if state.get('buy_pe_entered'):
        blocking_flags.append('buy_pe_entered=true')
    if state.get('sell_pe_entered'):
        blocking_flags.append('sell_pe_entered=true')
    
    if blocking_flags:
        print()
        print(" CRITICAL: Blocking flags detected!")
        print("   These flags prevent new trades:")
        for flag in blocking_flags:
            print(f"   - {flag}")
        print()
        print("   SOLUTION: Delete strategy_state.json or set RESET_STATE_ON_START=true")
    else:
        print(" No blocking flags found")
    
    # Check for saved tokens
    if state.get('otm_ce_token') and state.get('otm_pe_token'):
        print(f" Tokens saved: CE={state.get('otm_ce_token')}, PE={state.get('otm_pe_token')}")
    else:
        print(f" No tokens saved (Phase 1 may have failed)")
else:
    print(f"  No state file found (this is OK for first run)")

print()

# Check 2: Configuration
print("CHECK 2: CONFIGURATION")
print("-"*80)
print(f"TRADING_MODE: {Config.TRADING_MODE}")
print(f"DATA_MODE: {Config.DATA_MODE}")
print(f"RESET_STATE_ON_START: {Config.RESET_STATE_ON_START}")
print(f"DEBUG_MODE: {Config.DEBUG_MODE}")
print()

if not Config.RESET_STATE_ON_START and os.path.exists(Config.STATE_FILE):
    print("  WARNING: RESET_STATE_ON_START=false and state file exists")
    print("   Old state flags may prevent trading!")
    print("   SOLUTION: Set RESET_STATE_ON_START=true in .env")
else:
    print(" Configuration OK")

print()

# Check 3: Instruments
print("CHECK 3: INSTRUMENT DATA")
print("-"*80)
try:
    instruments = InstrumentMaster(str(Config.CSV_PATH))
    print(f" Loaded {len(instruments.data)} instruments")
    
    # Find nearest expiry
    from datetime import date
    today = date.today()
    
    # Get NIFTY options for nearest expiry
    nifty_options = [i for i in instruments.data.values() 
                     if i['name'] == 'NIFTY' and i['instrumenttype'] == 'OPTIDX']
    
    if nifty_options:
        # Group by expiry
        expiries = {}
        for opt in nifty_options:
            exp = opt['expiry']
            if exp not in expiries:
                expiries[exp] = []
            expiries[exp].append(opt)
        
        print(f" Found {len(nifty_options)} NIFTY options")
        print(f"   Available expiries: {sorted(expiries.keys())}")
        
        # Check nearest expiry
        nearest_expiry = min(expiries.keys())
        print(f"   Nearest expiry: {nearest_expiry}")
        print(f"   Options for nearest expiry: {len(expiries[nearest_expiry])}")
        
        # Sample some options
        sample_ce = [o for o in expiries[nearest_expiry] if 'CE' in o['symbol']][:5]
        sample_pe = [o for o in expiries[nearest_expiry] if 'PE' in o['symbol']][:5]
        
        print()
        print(f"   Sample CE options:")
        for opt in sample_ce:
            print(f"     {opt['symbol']} (Strike: {opt['strike']/100:.0f}, Token: {opt['token']})")
        
        print()
        print(f"   Sample PE options:")
        for opt in sample_pe:
            print(f"     {opt['symbol']} (Strike: {opt['strike']/100:.0f}, Token: {opt['token']})")
    else:
        print(" No NIFTY options found!")
        print("   SOLUTION: Update angel_master_instruments.csv")
    
except Exception as e:
    print(f" Error loading instruments: {e}")
    import traceback
    traceback.print_exc()

print()

# Check 4: Time Windows
print("CHECK 4: TIME WINDOWS")
print("-"*80)
from zoneinfo import ZoneInfo
now = datetime.now(Config.TZ)
current_time = now.time()

print(f"Current time (IST): {now.strftime('%H:%M:%S')}")
print()
print(f"Phase 0 window: {Config.PHASE0_START} - {Config.PHASE0_END}")
print(f"Phase 1 window: {Config.PHASE1_START} - {Config.PHASE1_END}")
print(f"Square-off time: {Config.SQUAREOFF_TIME}")
print()

# Determine current phase
if current_time < Config.PHASE0_START:
    print(f"  Market not open yet (opens at {Config.PHASE0_START})")
elif current_time >= Config.PHASE0_START and current_time < Config.PHASE0_END:
    print(f" Currently in PHASE 0 (Spot reference collection)")
elif current_time >= Config.PHASE1_START and current_time < Config.PHASE1_END:
    print(f" Currently in PHASE 1 (Strike selection)")
elif current_time >= Config.PHASE1_END and current_time < Config.SQUAREOFF_TIME:
    print(f" Currently in {PHASE_IN_TRADE} phase (entries possible)")
elif current_time >= Config.SQUAREOFF_TIME:
    print(f"  Past square-off time (no new entries)")
else:
    print(f"  Between Phase 0 and Phase 1")

print()

# Check 5: Entry Conditions
print("CHECK 5: ENTRY CONDITION PARAMETERS")
print("-"*80)
print(f"Target CE Delta: {Config.TARGET_CE_DELTA}")
print(f"Target PE Delta: {Config.TARGET_PE_DELTA}")
print(f"OTM Premium Range: {Config.OTM_PREMIUM_MIN} - {Config.OTM_PREMIUM_MAX}")
print()
print(f"SELL Entry Delay: {Config.SELL_ENTRY_DELAY}s")
print(f"SELL Decay Trigger: {Config.SELL_DECAY_TRIGGER}%")
print()
print(f"BUY Trigger Multiplier: {Config.BUY_TRIGGER_MULTIPLIER}x")
print(f"BUY Trigger Absolute: {Config.BUY_TRIGGER_ABSOLUTE}")
print()
print("For BUY entry, LTP must be >= (ref_premium * 1.8) + 2.0")
print()

# Summary
print("="*80)
print("DIAGNOSTIC SUMMARY")
print("="*80)
print()
print("Most Common Reasons for No Trades:")
print()
print("1.  BLOCKING STATE FLAGS")
print("   - phase1_done, buy_ce_entered, sell_ce_entered flags from old run")
print("   - Solution: Delete strategy_state.json OR set RESET_STATE_ON_START=true")
print()
print("2.  PHASE 1 FAILED")
print("   - Insufficient wait time for delta calculation (was 2s, now 10s in v2.4)")
print("   - No tokens saved -> no trading possible")
print("   - Solution: Upgrade to v2.4, check logs for 'DELTA SELECTED'")
print()
print("3.  WRONG TIME WINDOW")
print("   - Trading only between 09:16:15 and 15:25:00")
print("   - Solution: Run during market hours")
print()
print("4.  ENTRY CONDITIONS NOT MET")
print("   - SELL: Premium must decay by 2% from reference")
print("   - BUY: LTP must be >= (ref_premium * 1.8) + 2.0")
print("   - Solution: Check logs for condition checks, verify market movement")
print()
print("5.  NO INSTRUMENTS DATA")
print("   - Missing or outdated angel_master_instruments.csv")
print("   - Solution: Update CSV file")
print()
print("ACTION ITEMS:")
print("-"*80)

action_items = []

# Check for state issues
if os.path.exists(Config.STATE_FILE):
    with open(Config.STATE_FILE, 'r') as f:
        state = json.load(f)
    if state.get('phase1_done') or state.get('buy_ce_entered') or state.get('sell_ce_entered'):
        action_items.append(" DELETE strategy_state.json (or set RESET_STATE_ON_START=true)")

# Check config
if not Config.RESET_STATE_ON_START:
    action_items.append(" SET RESET_STATE_ON_START=true in .env file")

if Config.DEBUG_MODE is False:
    action_items.append(" ENABLE DEBUG_MODE=true for detailed logs")

if action_items:
    for item in action_items:
        print(item)
else:
    print(" No immediate action items")
    print("   If still no trades, check logs for:")
    print("   - 'PHASE1:  Sufficient data received'")
    print("   - ' DELTA SELECTED'")
    print("   - '[SELL_ENTRY_CHECK] CONDITION MET' or '[BUY_ENTRY_CHECK] CONDITION MET'")

print()
print("="*80)
