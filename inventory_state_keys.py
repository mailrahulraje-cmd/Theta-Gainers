#!/usr/bin/env python3
"""
Script to inventory all self.state.get(...) calls and extract unique keys.
"""
import re
from collections import Counter

with open("strategy/engine.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find all self.state.get(...) patterns
pattern = r"self\.state\.get\(\s*['\"]([^'\"]+)['\"]"
matches = re.findall(pattern, content)

# Count occurrences
key_counts = Counter(matches)

print("=== Full grep -nR self.state.get( output ===\n")
with open("strategy/engine.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
    
for i, line in enumerate(lines, 1):
    if "self.state.get(" in line:
        print(f"{i}:{line.rstrip()}")

print("\n=== Unique keys frequency (sorted by count) ===\n")
print("Count | Key")
print("------|" + "-" * 50)
for key, count in key_counts.most_common():
    print(f"{count:5d} | {key}")

print(f"\nTotal unique keys: {len(key_counts)}")
print(f"Total occurrences: {len(matches)}")
