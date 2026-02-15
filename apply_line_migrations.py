#!/usr/bin/env python3
"""
Apply migrations line-by-line, processing each line carefully.
Handles multiple state.get() calls on the same line correctly.
"""
import re
from pathlib import Path

SRC = Path("strategy/engine.py")
lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)

KEY_MAP = {
    'buy_ce_leg_ready': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_leg_ready': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_leg_ready': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_leg_ready': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'sell_ce_entered': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_entered': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'buy_ce_entered': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_entered': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_exited': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_exited': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'buy_ce_exited': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_exited': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_strike': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_strike': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'buy_ce_strike': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_strike': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_ref_premium': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_ref_premium': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'buy_ce_ref_premium': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_ref_premium': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_entry_price': 'self.trade_leg_manager.get_leg(\'sell_ce\')',
    'sell_pe_entry_price': 'self.trade_leg_manager.get_leg(\'sell_pe\')',
    'buy_ce_entry_price': 'self.trade_leg_manager.get_leg(\'buy_ce\')',
    'buy_pe_entry_price': 'self.trade_leg_manager.get_leg(\'buy_pe\')',
    'sell_ce_token': 'self.trade_leg_manager.get_leg(\'sell_ce\').token',
    'sell_pe_token': 'self.trade_leg_manager.get_leg(\'sell_pe\').token',
    'buy_ce_token': 'self.trade_leg_manager.get_leg(\'buy_ce\').token',
    'buy_pe_token': 'self.trade_leg_manager.get_leg(\'buy_pe\').token',
}

migrations = 0
total_lines = len(lines)

for line_idx in range(total_lines):
    line = lines[line_idx]
    modified = False
    
    # Keep replacing on this line until no more patterns found
    while True:
        # Find one state.get() pattern (exact, single occurrence)
        match = re.search(r"self\.state\.get\('([^']+)',?\s*[^)]*\)", line)
        if not match:
            break
        
        key = match.group(1)
        if key not in KEY_MAP:
            # Skip non-migrable keys like 'phase', 'lot_size', etc.
            break
        
        # Replace just this match
        replacement = KEY_MAP[key]
        line = line[:match.start()] + replacement + line[match.end():]
        migrations += 1
        modified = True
    
    if modified:
        lines[line_idx] = line
        if migrations <= 15 or migrations % 15 == 0:
            print(f"[{migrations}] Line {line_idx + 1} migrated")

SRC.write_text("".join(lines), encoding="utf-8")

final_count = sum(1 for line in lines if "self.state.get(" in line)
print(f"\nSummary:")
print(f"  Migrations applied: {migrations}")
print(f"  Remaining state.get() calls: {final_count}")
print(f"\nFile updated: {SRC}")
