# STATE.GET() MIGRATION PLAN FOR strategy/engine.py
# Safe, Reviewable Automated Migration Strategy

## A. INVENTORY RESULTS

**Total Unique Keys:** 37  
**Total Occurrences:** (counted from full grep output above, ~125+ calls)

**Top 10 Most Frequent Keys (by occurrence count):**

| Count | Key | Example Lines |
|-------|-----|---|
| 8 | phase | 399, 659, 667, 677, 688, 694, 1370, 1843 |
| 7 | buy_ce_leg_ready | 810, 892, 973, 1006, 1046, 1057, 1190 |
| 7 | buy_pe_leg_ready | 810, 896, 988, 1006, 1047, 1058, 1194 |
| 5 | sell_ce_strike | 819, 1018, 1174, 1496, 1516 |
| 5 | sell_pe_strike | 821, 1020, 1178, 1499, 1513 |
| 5 | sell_pe_entered | 1155, 1167, 1171, 1712, 1766 |
| 4 | trade_state | 177, 280, 1117, 1263 |
| 4 | phase1_done | 628, 666, 676, 811, 844 |
| 4 | sell_ce_entered | 1154, 1163, 1171, 1743 |
| 4 | lot_size | 1241, 1331, 1550, 1586 |

---

## B. MAPPING TABLE (Top 10 Keys)

| State Key | Logical Purpose | TradeLegManager Call | TradeLegV1 Field(s) | Fallback Legacy Key | Migration Type |
|-----------|-----------------|---------------------|---------------------|---------------------|-----------------|
| `phase` | Current trading phase | N/A (use phase_manager) | `self.phase_manager.phase` | `phase` | **Config/Phase** |
| `buy_ce_leg_ready` | BUY CE leg readiness | `self.trade_leg_manager.get_leg('buy_ce')` | Check `is not None` | `buy_ce_leg_ready` | **Leg Status** |
| `buy_pe_leg_ready` | BUY PE leg readiness | `self.trade_leg_manager.get_leg('buy_pe')` | Check `is not None` | `buy_pe_leg_ready` | **Leg Status** |
| `sell_ce_strike` | SELL CE strike price | `self.trade_leg_manager.get_leg('sell_ce')` | N/A (metadata only) | `sell_ce_strike` | **Leg Metadata** |
| `sell_pe_strike` | SELL PE strike price | `self.trade_leg_manager.get_leg('sell_pe')` | N/A (metadata only) | `sell_pe_strike` | **Leg Metadata** |
| `sell_pe_entered` | SELL PE entry status | `self.trade_leg_manager.get_leg('sell_pe')` | Check `is not None` + trade_state | `sell_pe_entered` | **Leg Status** |
| `trade_state` | Dict of leg states | Already type-safe via cast | `self.state.state['trade_state']` | `trade_state` | **Struct** |
| `phase1_done` | Phase 1 completion flag | Already checked via leg readiness | N/A (derive from legs) | `phase1_done` | **State Flag** |
| `sell_ce_entered` | SELL CE entry status | `self.trade_leg_manager.get_leg('sell_ce')` | Check `is not None` + trade_state | `sell_ce_entered` | **Leg Status** |
| `lot_size` | Lot size metadata | Retrieve from `Config.LOTS` or state['lot_size'] | Metadata field | `lot_size` | **Config Value** |

---

## C. REPLACEMENT RULES & STRATEGY

### Core Rules:

1. **Prefer TradeLegManager for leg-related keys**
   - Use `self.trade_leg_manager.get_leg('leg_name')` for any key matching pattern `{leg}_*`
   - Examples: `sell_ce_token`, `buy_pe_entered`, `sell_pe_strike`

2. **Explicit None-Check Pattern**
   - For mandatory legs: check `if leg is None:`, log error, and `raise RuntimeError("Missing mandatory leg: ...")`
   - For optional metadata: log warning and continue with None value or default

3. **Field Access from TradeLegV1**
   - `token` → leg.token
   - `quantity` → leg.quantity
   - `entry_price` → leg.entry_price
   - Other metadata → fallback to legacy `state.get('key')` but mark with TODO

4. **Phase Management**
   - For `phase` or `phase*_done`: do NOT migrate to TradeLegManager
   - Instead: use `self.state.get('phase')` (already wrapped with proper validation in core/state.py)
   - Add comment: `# Phase managed by StrategyState wrapper; not leg-specific`

5. **Config/Metadata Keys**
   - For `lot_size`, `atm_strike`, `expiry`: retrieve from `Config` or `state['lot_size']`
   - These are NOT leg-specific; leave as-is but add comment for clarity

6. **Comment Strategy**
   - Add `# TODO MIGRATE: <KEY> from legacy state.get() to type-safe accessor` above each replacement
   - For ambiguous mappings: add `# TODO REVIEW: mapping confidence=manual; confirm field access`

7. **Variable Naming**
   - Preserve original variable names (e.g., `tok_ce`, `ref`, `strike`) where possible
   - Makes diffs minimal and code-review easier

### Mandatory vs Optional Handling:

**Mandatory Keys** (raise if missing):
- `sell_ce_token`, `sell_pe_token`, `buy_ce_token`, `buy_pe_token` (must exist for active legs)
- `sell_ce_strike`, `sell_pe_strike`, `buy_ce_strike`, `buy_pe_strike`

**Optional Keys** (log warning, continue with None):
- `sell_ce_entry_price`, `buy_ce_entry_price` (optional fields)
- `_phase1_attempt_count`, `hard_exit_blocked` (internal flags)

---

## D. PATCH GENERATION SCRIPT

Below is a Python script that **generates but does NOT apply** patches. It:
- Scans `strategy/engine.py` for `self.state.get('KEY', ...)` patterns
- For each occurrence, proposes a type-safe snippet with TODO comment
- Writes a separate `patch_suggest_<n>.diff` file for each unique context
- Produces `migration_suggestions.csv` with a summary

**Script: `generate_migration_patches.py`**

```python
#!/usr/bin/env python3
"""
Generate reviewable migration patches for self.state.get() -> type-safe accessors.
Does NOT auto-apply; produces patch files for manual review.
"""
import re
import csv
from pathlib import Path
from collections import defaultdict

# Mapping of state keys to suggested replacements
KEY_MAPPING = {
    # Leg tokens (mandatory)
    'sell_ce_token': ('sell_ce', 'token', 'mandatory'),
    'sell_pe_token': ('sell_pe', 'token', 'mandatory'),
    'buy_ce_token': ('buy_ce', 'token', 'mandatory'),
    'buy_pe_token': ('buy_pe', 'token', 'mandatory'),
    
    # Leg readiness (leg life-cycle status)
    'sell_ce_leg_ready': ('sell_ce', 'status', 'optional'),
    'sell_pe_leg_ready': ('sell_pe', 'status', 'optional'),
    'buy_ce_leg_ready': ('buy_ce', 'status', 'optional'),
    'buy_pe_leg_ready': ('buy_pe', 'status', 'optional'),
    
    # Leg entry status
    'sell_ce_entered': ('sell_ce', 'entered', 'optional'),
    'sell_pe_entered': ('sell_pe', 'entered', 'optional'),
    'buy_ce_entered': ('buy_ce', 'entered', 'optional'),
    'buy_pe_entered': ('buy_pe', 'entered', 'optional'),
    
    # Leg exit status
    'sell_ce_exited': ('sell_ce', 'exited', 'optional'),
    'sell_pe_exited': ('sell_pe', 'exited', 'optional'),
    'buy_ce_exited': ('buy_ce', 'exited', 'optional'),
    'buy_pe_exited': ('buy_pe', 'exited', 'optional'),
    
    # Leg strike prices (metadata)
    'sell_ce_strike': ('sell_ce', 'metadata', 'optional'),
    'sell_pe_strike': ('sell_pe', 'metadata', 'optional'),
    'buy_ce_strike': ('buy_ce', 'metadata', 'optional'),
    'buy_pe_strike': ('buy_pe', 'metadata', 'optional'),
    
    # Leg reference premiums (metadata)
    'sell_ce_ref_premium': ('sell_ce', 'metadata', 'optional'),
    'sell_pe_ref_premium': ('sell_pe', 'metadata', 'optional'),
    'buy_ce_ref_premium': ('buy_ce', 'metadata', 'optional'),
    'buy_pe_ref_premium': ('buy_pe', 'metadata', 'optional'),
    
    # Leg entry prices (metadata)
    'sell_ce_entry_price': ('sell_ce', 'metadata', 'optional'),
    'sell_pe_entry_price': ('sell_pe', 'metadata', 'optional'),
    'buy_ce_entry_price': ('buy_ce', 'metadata', 'optional'),
    'buy_pe_entry_price': ('buy_pe', 'metadata', 'optional'),
    
    # Non-leg keys (special handling)
    'phase': (None, 'phase', 'no_migrate'),
    'phase0_done': (None, 'state_flag', 'no_migrate'),
    'phase1_done': (None, 'state_flag', 'no_migrate'),
    'trade_state': (None, 'struct', 'no_migrate'),
    'initialized': (None, 'flag', 'no_migrate'),
    'hard_exit_blocked': (None, 'flag', 'no_migrate'),
    'hard_exit_no_new_entries': (None, 'flag', 'no_migrate'),
    'lot_size': (None, 'config', 'no_migrate'),
    'atm_strike': (None, 'metadata', 'no_migrate'),
    'expiry': (None, 'metadata', 'no_migrate'),
    'squareoff_done': (None, 'flag', 'no_migrate'),
}

def generate_suggestion(leg_name, field_type, mandatory_level, state_key):
    """Generate a type-safe suggestion snippet."""
    if leg_name is None:
        # Non-leg keys; no auto-migration suggested
        return None, f"MAPPING=MANUAL (non-leg key: {state_key})"
    
    if mandatory_level == 'mandatory':
        suggestion = f"""# TODO MIGRATE: '{state_key}' from legacy state.get() to type-safe accessor
leg = self.trade_leg_manager.get_leg('{leg_name}')
if leg is None:
    logger.error("Missing mandatory leg: {leg_name}")
    raise RuntimeError("Missing mandatory leg: {leg_name}")
tok = leg.token"""
        return suggestion, f"MAPPING=TradeLegManager.get_leg('{leg_name}').token"
    else:
        suggestion = f"""# TODO MIGRATE: '{state_key}' from legacy state.get() to type-safe accessor
leg = self.trade_leg_manager.get_leg('{leg_name}')
if leg is not None:
    # TODO REVIEW: access appropriate field from TradeLegV1
    value = getattr(leg, '{field_type}', None)
else:
    value = None  # Fallback: leg not ready"""
        return suggestion, f"MAPPING=TradeLegManager.get_leg('{leg_name}') with fallback"

def main():
    engine_path = Path("strategy/engine.py")
    with open(engine_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Regex to find self.state.get( patterns
    pattern = r"self\.state\.get\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*([^)]+))?\)"
    
    patches = []
    csv_rows = []
    patch_counter = 0
    
    for i, line in enumerate(lines):
        matches = re.finditer(pattern, line)
        for match in matches:
            state_key = match.group(1)
            default_val = match.group(2) if match.group(2) else "None"
            
            if state_key not in KEY_MAPPING:
                # Unknown key; skip
                csv_rows.append({
                    'file': 'strategy/engine.py',
                    'line_start': i+1,
                    'line_end': i+1,
                    'state_key': state_key,
                    'suggested_patch_file': f'SKIP_UNKNOWN_{state_key}',
                    'mapping': 'UNKNOWN_KEY'
                })
                continue
            
            leg_name, field_type, mandatory = KEY_MAPPING[state_key]
            suggestion, mapping_note = generate_suggestion(leg_name, field_type, mandatory, state_key)
            
            if suggestion is None:
                # Non-migrable key
                csv_rows.append({
                    'file': 'strategy/engine.py',
                    'line_start': i+1,
                    'line_end': i+1,
                    'state_key': state_key,
                    'suggested_patch_file': f'NO_PATCH_{state_key.upper()}',
                    'mapping': mapping_note
                })
                continue
            
            # Create patch
            patch_counter += 1
            patch_filename = f"patch_suggest_{patch_counter:03d}.diff"
            
            # Get context (3 lines before, 3 lines after)
            start_ctx = max(0, i - 3)
            end_ctx = min(len(lines), i + 4)
            
            patch_content = f"""--- a/strategy/engine.py
+++ b/strategy/engine.py
@@ -{i+1},{end_ctx-start_ctx+1} +{i+1},{end_ctx-start_ctx+1} @@
"""
            for ctx_i in range(start_ctx, end_ctx):
                if ctx_i == i:
                    patch_content += f"-{lines[ctx_i]}"
                    patch_content += f"+{suggestion}\n"
                else:
                    patch_content += f" {lines[ctx_i]}"
            
            patch_path = Path(patch_filename)
            patch_path.write_text(patch_content)
            
            csv_rows.append({
                'file': 'strategy/engine.py',
                'line_start': i+1,
                'line_end': i+1,
                'state_key': state_key,
                'suggested_patch_file': patch_filename,
                'mapping': mapping_note
            })
            print(f"[{patch_counter:03d}] Generated patch for '{state_key}' at line {i+1} -> {patch_filename}")
    
    # Write CSV summary
    csv_path = Path("migration_suggestions.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=['file', 'line_start', 'line_end', 'state_key', 'suggested_patch_file', 'mapping'])
        writer.writeheader()
        writer.writerows(csv_rows)
    
    print(f"\n✅ Generated {patch_counter} patch files and migration_suggestions.csv")
    print(f"Review patches, then apply with: git apply --check patch_suggest_NNN.diff && git apply patch_suggest_NNN.diff")

if __name__ == "__main__":
    main()
```

Save this as `generate_migration_patches.py` and run:
```bash
python generate_migration_patches.py
```

---

## E. USAGE GUIDE

### Step 1: Generate Patch Suggestions
```bash
python generate_migration_patches.py
```

**Output:**
- `patch_suggest_001.diff`, `patch_suggest_002.diff`, etc. (one per migrable occurrence)
- `migration_suggestions.csv` (summary table)
- Console output listing generated patches

### Step 2: Review Patches One-by-One
```bash
# Look at the migration summary
cat migration_suggestions.csv | head -20

# Review a specific patch before applying
cat patch_suggest_001.diff
```

### Step 3: Validate Patch Syntax
```bash
# Check if patch can be applied (dry-run)
git apply --check patch_suggest_001.diff

# If OK, apply the patch
git apply patch_suggest_001.diff

# Stage and commit
git add strategy/engine.py
git commit -m "Migrate state.get('KEY') -> type-safe accessor (patch_suggest_001)"
```

### Step 4: Test After Each Patch
```bash
# Run unit tests to verify no regressions
python -m pytest test_state_validation.py -v

# Run verification script
python verify_state_migration_fix.py
```

### Step 5: Repeat for Multiple Patches
Apply patches in sequence (low-risk first):
1. Start with **optional** keys (leg_ready, entered, exited)
2. Then **metadata** keys (strike, entry_price)
3. Finally **mandatory** keys (token)

---

## F. REVIEWER CHECKLIST

### Before Applying Each Patch:

- [ ] **Syntax Check**: `git apply --check patch_suggest_NNN.diff` passes
- [ ] **Field Name Verification**: Confirm TradeLegV1 has the field being accessed
  ```bash
  grep -A 30 "class TradeLegV1" contract.py | grep "token\|quantity\|entry_price"
  ```
- [ ] **Semantics Confirmation**: Patch correctly maps original logic to type-safe access
- [ ] **None-Check Present**: For mandatory legs, verify `if leg is None: raise RuntimeError(...)`
- [ ] **Variable Names Preserved**: Original variable names unchanged (e.g., `tok_ce` stays `tok_ce`)
- [ ] **Context Readability**: First 3 lines of diff context match actual file at that line number

### After Applying Patch:

- [ ] **Git Status Clean**: `git status` shows only `strategy/engine.py` modified
- [ ] **No Syntax Errors**: `python -m py_compile strategy/engine.py` succeeds
- [ ] **Unit Tests Pass**: `python -m pytest test_state_validation.py` or similar
- [ ] **Verification Script Pass**: `python verify_state_migration_fix.py` shows all criteria passed
- [ ] **Grep Confirms Migration**: Run `grep -n "state.get('KEY')" strategy/engine.py` — should show fewer occurrences

### Rollback If Issues:

```bash
# If patch causes errors, revert
git reset HEAD~1
git checkout strategy/engine.py
```

---

## G. SUMMARY & NEXT STEPS

**Status:** 37 unique state keys identified, 125+ occurrences found.

**High-Priority Migrations (Top 10):**
1. `phase` — NO MIGRATE (already wrapped in StrategyState)
2. `buy_ce_leg_ready` → TradeLegManager ('buy_ce') status check
3. `buy_pe_leg_ready` → TradeLegManager ('buy_pe') status check
4. `sell_ce_strike` → TradeLegManager ('sell_ce') + fallback to state
5. `sell_pe_strike` → TradeLegManager ('sell_pe') + fallback to state
6. `sell_pe_entered` → TradeLegManager ('sell_pe') status check
7. `trade_state` — NO MIGRATE (already struct; use state.state['trade_state'])
8. `phase1_done` — NO MIGRATE (state flag; derive from leg readiness)
9. `sell_ce_entered` → TradeLegManager ('sell_ce') status check
10. `lot_size` — NO MIGRATE (Config or metadata)

**Recommended Approach:**
1. Run `generate_migration_patches.py` to create patch files
2. Review each patch using the reviewer checklist
3. Apply patches in small batches (3-5 per batch)
4. Run tests after each batch
5. Create separate commits for logical groups (e.g., all sell_ce, all buy_ce, etc.)

---

**DO NOT AUTO-APPLY** any patches until manually reviewed and confirmed safe.
