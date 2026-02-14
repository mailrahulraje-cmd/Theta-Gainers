#!/usr/bin/env python3
"""
Check if system is ready to enter trades
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import Config
from constants import PHASE_IN_TRADE, PHASE_PHASE1

print("="*80)
print("TRADE ENTRY READINESS CHECK")
print("="*80)
print()

# Check state file
if not os.path.exists(Config.STATE_FILE):
    print(" No state file found")
    print("   Run the system during Phase 1 window (09:16:05-09:16:15)")
    sys.exit(1)

with open(Config.STATE_FILE, 'r') as f:
    state = json.load(f)

# LEGACY FORMAT DETECTION
legacy_flags = [k for k in state.keys() if k.endswith('_leg_ready')]
flat_flags = [k for k in state.keys() if k in ['sell_ce_entered', 'sell_pe_entered', 'buy_ce_entered', 'buy_pe_entered']]

if flat_flags and not legacy_flags:
    print("  LEGACY STATE FORMAT DETECTED")
    print("   State file uses flat boolean flags (legacy format)")
    print("   Consider migrating to structured leg state for better resilience")
    print()

print("CURRENT STATE:")
print("-"*80)
for key, value in sorted(state.items()):
    print(f"  {key}: {value}")
print()

# Check Phase 1 completion
if not state.get('phase1_done'):
    print(" Phase 1 NOT complete")
    print("   System needs to run during 09:16:05-09:16:15")
    sys.exit(1)

print(" Phase 1 completed")
print()

# Check tokens
ce_token = state.get('otm_ce_token')
pe_token = state.get('otm_pe_token')

if not ce_token or not pe_token:
    print(" No tokens saved")
    print(f"   CE Token: {ce_token}")
    print(f"   PE Token: {pe_token}")
    sys.exit(1)

print(f" Tokens saved:")
print(f"   CE Token: {ce_token}")
print(f"   PE Token: {pe_token}")
print()

# Check reference premiums
ce_ref = state.get('otm_ce_ref_premium')
pe_ref = state.get('otm_pe_ref_premium')

if not ce_ref or not pe_ref:
    print(" No reference premiums saved")
    sys.exit(1)

print(f" Reference premiums:")
print(f"   CE: {ce_ref:.2f}")
print(f"   PE: {pe_ref:.2f}")
print()

# Check entry flags
sell_ce = state.get('sell_ce_entered', False)
sell_pe = state.get('sell_pe_entered', False)
buy_ce = state.get('buy_ce_entered', False)
buy_pe = state.get('buy_pe_entered', False)

print("ENTRY STATUS:")
print("-"*80)
print(f"  SELL CE: {' Entered' if sell_ce else ' Waiting'}")
print(f"  SELL PE: {' Entered' if sell_pe else ' Waiting'}")
print(f"  BUY CE:  {' Entered' if buy_ce else ' Waiting'}")
print(f"  BUY PE:  {' Entered' if buy_pe else ' Waiting'}")
print()

# Calculate entry conditions
print("ENTRY TRIGGER CALCULATIONS:")
print("-"*80)

# SELL triggers
sell_ce_trigger = ce_ref * (1 - Config.SELL_DECAY_TRIGGER / 100)
sell_pe_trigger = pe_ref * (1 - Config.SELL_DECAY_TRIGGER / 100)

print(f"SELL CE trigger: {sell_ce_trigger:.2f} (LTP must be  this)")
print(f"SELL PE trigger: {sell_pe_trigger:.2f} (LTP must be  this)")
print()

# BUY triggers  
buy_ce_trigger = (ce_ref * Config.BUY_TRIGGER_MULTIPLIER) + Config.BUY_TRIGGER_ABSOLUTE
buy_pe_trigger = (pe_ref * Config.BUY_TRIGGER_MULTIPLIER) + Config.BUY_TRIGGER_ABSOLUTE

print(f"BUY CE trigger: {buy_ce_trigger:.2f} (LTP must be  this)")
print(f"BUY PE trigger: {buy_pe_trigger:.2f} (LTP must be  this)")
print()

# Time check
from zoneinfo import ZoneInfo
now = datetime.now(Config.T