import re
import sys

with open("strategy/engine.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Step 3: Find all self.state.get( patterns
print("=== Step 3: All self.state.get( occurrences ===")
matches = []
for i, line in enumerate(lines, 1):
    if "self.state.get(" in line:
        matches.append((i, line.rstrip()))

print(f"\nTotal count: {len(matches)}")
print(f"\nAll occurrences:")
for line_num, line_text in matches:
    print(f"{line_num}:{line_text}")

# Show top 20 with 3 lines context
print(f"\n=== Top 20 representative occurrences with 3-line context ===")
for idx, (line_num, line_text) in enumerate(matches[:20]):
    start = max(0, line_num - 4)
    end = min(len(lines), line_num + 2)
    print(f"\n--- Occurrence {idx+1} (line {line_num}) ---")
    for i in range(start, end):
        prefix = ">>> " if (i+1) == line_num else "    "
        print(f"{prefix}{i+1}:{lines[i].rstrip()}")

# Step 4: Verify sell_ce replacement
print(f"\n=== Step 4: Verification Queries ===")
print("\nGrep for 'sell_ce_token' unsafe access:")
sell_ce_token_matches = []
for i, line in enumerate(lines, 1):
    if "sell_ce_token" in line:
        sell_ce_token_matches.append((i, line.rstrip()))
for line_num, line_text in sell_ce_token_matches:
    print(f"{line_num}:{line_text}")

print(f"\nGrep for 'trade_leg_manager.get_leg('sell_ce')' (safe access):")
safe_sell_ce_matches = []
for i, line in enumerate(lines, 1):
    if "trade_leg_manager.get_leg('sell_ce')" in line:
        safe_sell_ce_matches.append((i, line.rstrip()))
for line_num, line_text in safe_sell_ce_matches:
    print(f"{line_num}:{line_text}")

# Show sed -n '1688,1700p' output
print(f"\n=== sed -n '1688,1700p' strategy/engine.py ===")
for i in range(1688-1, 1700):
    if i < len(lines):
        print(f"{i+1}:{lines[i].rstrip()}")
