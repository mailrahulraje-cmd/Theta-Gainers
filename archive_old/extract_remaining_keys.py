#!/usr/bin/env python3
"""Extract remaining (non-migrated) state keys from migration_suggestions.csv"""
import csv

keys_set = set()

with open("migration_suggestions.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = row['state_key'].strip()
        status = row['mapping_status'].strip()
        rec = row['recommendation'].strip()
        
        if status == "NO_AUTO_PATCH" and rec == "KEEP_AS_IS":
            keys_set.add(key)

print("Unique KEEP_AS_IS keys (34 remaining non-leg state keys):\n")
for i, key in enumerate(sorted(keys_set), 1):
    print(f"{i:2d}. {key}")

print(f"\nTotal unique keys marked KEEP_AS_IS: {len(keys_set)}")
