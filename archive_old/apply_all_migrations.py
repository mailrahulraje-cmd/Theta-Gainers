#!/usr/bin/env python3
"""
Apply all remaining state.get() migrations directly to strategy/engine.py
This avoids patch conflicts from overlapping patterns on same lines.
"""
import re
from pathlib import Path

SRC = Path("strategy/engine.py")
text = SRC.read_text(encoding="utf-8")
original_count = len(re.findall(r"self\.state\.get\(", text))

# Mapping of keys to migrate
KEY_MAP = {
    # Leg tokens
    'buy_ce_leg_ready': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_leg_ready': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_leg_ready': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_leg_ready': "self.trade_leg_manager.get_leg('sell_pe')",
    'sell_ce_entered': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_entered': "self.trade_leg_manager.get_leg('sell_pe')",
    'buy_ce_entered': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_entered': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_exited': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_exited': "self.trade_leg_manager.get_leg('sell_pe')",
    'buy_ce_exited': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_exited': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_strike': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_strike': "self.trade_leg_manager.get_leg('sell_pe')",
    'buy_ce_strike': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_strike': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_ref_premium': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_ref_premium': "self.trade_leg_manager.get_leg('sell_pe')",
    'buy_ce_ref_premium': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_ref_premium': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_entry_price': "self.trade_leg_manager.get_leg('sell_ce')",
    'sell_pe_entry_price': "self.trade_leg_manager.get_leg('sell_pe')",
    'buy_ce_entry_price': "self.trade_leg_manager.get_leg('buy_ce')",
    'buy_pe_entry_price': "self.trade_leg_manager.get_leg('buy_pe')",
    'sell_ce_token': "self.trade_leg_manager.get_leg('sell_ce').token",
    'sell_pe_token': "self.trade_leg_manager.get_leg('sell_pe').token",
    'buy_ce_token': "self.trade_leg_manager.get_leg('buy_ce').token",
    'buy_pe_token': "self.trade_leg_manager.get_leg('buy_pe').token",
}

migrations = 0
for key, replacement in KEY_MAP.items():
    pattern = f"self\\.state\\.get\\('{key}'(?:,\\s*[^)]*)?\\)"
    matches = list(re.finditer(pattern, text))
    for match in matches:
        # Replace this specific occurrence
        text = text[:match.start()] + replacement + text[match.end():]
        migrations += 1
        print(f"[{migrations}] Migrated '{key}' at position {match.start()}")

SRC.write_text(text, encoding="utf-8")

final_count = len(re.findall(r"self\.state\.get\(", text))
print(f"\nSummary:")
print(f"  Original occurrences: {original_count}")
print(f"  Migrations applied: {migrations}")
print(f"  Remaining occurrences: {final_count}")
print(f"\nFile updated: {SRC}")
