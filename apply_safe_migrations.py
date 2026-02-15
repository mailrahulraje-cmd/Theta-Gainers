#!/usr/bin/env python3
"""
Apply migrations in REVERSE order (highest position first) to avoid position shift issues.
"""
import re
from pathlib import Path

SRC = Path("strategy/engine.py")
text = SRC.read_text(encoding="utf-8")
original_count = len(re.findall(r"self\.state\.get\(", text))

# Find ALL occurrences of state.get() calls
pattern = r"self\.state\.get\('([^']+)'(?:,\s*[^)]*)?(\))"
matches = list(re.finditer(pattern, text))

print(f"Found {len(matches)} state.get() patterns")
print(f"Processing in REVERSE order to avoid position shifts...\n")

# Map of keys to migrate
KEY_MAP = {
    'buy_ce_leg_ready': ('buy_ce', 'status'),
    'buy_pe_leg_ready': ('buy_pe', 'status'),
    'sell_ce_leg_ready': ('sell_ce', 'status'),
    'sell_pe_leg_ready': ('sell_pe', 'status'),
    'sell_ce_entered': ('sell_ce', 'None'),
    'sell_pe_entered': ('sell_pe', 'None'),
    'buy_ce_entered': ('buy_ce', 'None'),
    'buy_pe_entered': ('buy_pe', 'None'),
    'sell_ce_exited': ('sell_ce', 'None'),
    'sell_pe_exited': ('sell_pe', 'None'),
    'buy_ce_exited': ('buy_ce', 'None'),
    'buy_pe_exited': ('buy_pe', 'None'),
    'sell_ce_strike': ('sell_ce', 'None'),
    'sell_pe_strike': ('sell_pe', 'None'),
    'buy_ce_strike': ('buy_ce', 'None'),
    'buy_pe_strike': ('buy_pe', 'None'),
    'sell_ce_ref_premium': ('sell_ce', 'None'),
    'sell_pe_ref_premium': ('sell_pe', 'None'),
    'buy_ce_ref_premium': ('buy_ce', 'None'),
    'buy_pe_ref_premium': ('buy_pe', 'None'),
    'sell_ce_entry_price': ('sell_ce', 'None'),
    'sell_pe_entry_price': ('sell_pe', 'None'),
    'buy_ce_entry_price': ('buy_ce', 'None'),
    'buy_pe_entry_price': ('buy_pe', 'None'),
    'sell_ce_token': ('sell_ce', 'token'),
    'sell_pe_token': ('sell_pe', 'token'),
    'buy_ce_token': ('buy_ce', 'token'),
    'buy_pe_token': ('buy_pe', 'token'),
}

migrations = 0

# Process matches in REVERSE order to avoid position shifts
for match in reversed(matches):
    key = match.group(1)
    closing_paren = match.group(2)
    
    if key not in KEY_MAP:
        # Don't migrate this key; it's 'phase', 'lot_size', etc.
        continue
    
    leg_name, field = KEY_MAP[key]
    
    # Build replacement
    if field == 'token':
        replacement = f"self.trade_leg_manager.get_leg('{leg_name}').token{closing_paren}"
    else:
        replacement = f"self.trade_leg_manager.get_leg('{leg_name}'){closing_paren}"
    
    # Replace this SINGLE match
    text = text[:match.start()] + replacement + text[match.end():]
    migrations += 1
    if migrations <= 10 or migrations % 10 == 0:
        print(f"[{migrations}] Migrated '{key}' at position {match.start()}")

print("\nFinal processing...")
SRC.write_text(text, encoding="utf-8")

final_count = len(re.findall(r"self\.state\.get\(", text))
print(f"\nSummary:")
print(f"  Original occurrences: {original_count}")
print(f"  Migrations applied: {migrations}")
print(f"  Remaining occurrences: {final_count}")
print(f"\nFile updated: {SRC}")
