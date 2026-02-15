# COMPREHENSIVE STATE.GET() MIGRATION PLAN
## Evidence & Review Documentation

**Generated:** February 15, 2026  
**File:** strategy/engine.py  
**Status:** ✅ Plan finalized (NO PATCHES APPLIED)

---

## SECTION A: INVENTORY RESULTS

### A.1 Full grep Output

All 125+ occurrences of `self.state.get(...)` in strategy/engine.py:

```
Line 177:  state=self.state.get('trade_state', {}) or {}
Line 270:  if not self.state.get('initialized'):
Line 280:  state_dict = self.state.get('trade_state', {}) or {}
Line 399:  current_phase = self.state.get('phase')
Line 441:  last_modify_time = self.state.get(last_modify_key)
Line 474:  strike = self.state.get(f'{leg_key}_strike', 0)
Line 496:  strike = self.state.get(f'{leg_key}_strike', 0)
Line 620:  if self.state.get('phase0_done'):
Line 622:  tok = self.state.get(key)
Line 623:  sym = self.state.get(key.replace('_token', '_symbol'))
Line 628:  if self.state.get('phase1_done'):
Line 630:  tok = self.state.get(key)
Line 631:  sym = self.state.get(key.replace('_token', '_symbol'))
Line 659:  if self.state.get('phase') != PHASE_STANDBY:
Line 666:  if not self.state.get('phase0_done'):
Line 667:  if self.state.get('phase') != PHASE_PHASE0:
Line 676:  if not self.state.get('phase1_done'):
Line 677:  if self.state.get('phase') != PHASE_PHASE1:
Line 688:  if self.state.get('phase') != PHASE_IN_TRADE:
Line 694:  if self.state.get('phase') != PHASE_CLOSED:
[... 105+ more occurrences ...]
(See full list in output above)
```

### A.2 Unique Keys Frequency (Sorted by Count)

```
Count | State Key
------|--------------------------------------------------
    8 | phase
    7 | buy_ce_leg_ready
    7 | buy_pe_leg_ready
    5 | sell_ce_strike
    5 | sell_pe_strike
    5 | sell_pe_entered
    4 | trade_state
    4 | phase1_done
    4 | sell_ce_entered
    4 | lot_size
    2 | phase0_done
    2 | sell_ce_ref_premium
    2 | sell_pe_ref_premium
    2 | buy_ce_strike
    2 | buy_ce_ref_premium
    2 | buy_pe_strike
    2 | buy_pe_ref_premium
    2 | hard_exit_blocked
    2 | sell_ce_leg_ready
    2 | sell_pe_leg_ready
    2 | sell_ce_entry_price
    2 | sell_pe_entry_price
    2 | sell_pe_exited
    2 | sell_pe_token
    1 | initialized
    1 | _phase1_attempt_count
    1 | atm_strike
    1 | expiry
    1 | _phase1_buy_ce_attempts
    1 | _phase1_buy_pe_attempts
    1 | _phase1_buy_ce_final_status
    1 | _phase1_buy_pe_final_status
    1 | hard_exit_no_new_entries
    1 | buy_ce_entered
    1 | buy_pe_entered
    1 | sell_ce_exited
    1 | sell_ce_token
```

**Summary:**
- **Total Unique Keys:** 37
- **Total Occurrences:** 125+
- **Leg-Related Keys:** ~24 (candidates for TradeLegManager migration)
- **Non-Leg Keys (config/state flags):** ~13 (keep as-is or safe accessors)

---

## SECTION B: MAPPING TABLE (Top 10 Keys)

| # | State Key | Type | Occurrence Count | TradeLegManager Call | Safe Field Access | Fallback | Migration Priority |
|---|-----------|------|------------------|---------------------|-------------------|----------|-------------------|
| 1 | `phase` | Config/Phase | 8 | N/A (phasemanager) | self.state.get('phase') | N/A | **SKIP** (already safe) |
| 2 | `buy_ce_leg_ready` | Leg Status | 7 | get_leg('buy_ce') | is not None | fallback boolean | **MEDIUM** (optional) |
| 3 | `buy_pe_leg_ready` | Leg Status | 7 | get_leg('buy_pe') | is not None | fallback boolean | **MEDIUM** (optional) |
| 4 | `sell_ce_strike` | Leg Metadata | 5 | get_leg('sell_ce') | N/A (external) | state.get(...) | **LOW** (metadata only) |
| 5 | `sell_pe_strike` | Leg Metadata | 5 | get_leg('sell_pe') | N/A (external) | state.get(...) | **LOW** (metadata only) |
| 6 | `sell_pe_entered` | Leg Status | 5 | get_leg('sell_pe') | is not None | fallback boolean | **MEDIUM** (optional) |
| 7 | `trade_state` | Struct | 4 | N/A (dict) | self.state.state['trade_state'] | N/A | **SKIP** (already typed) |
| 8 | `phase1_done` | State Flag | 4 | N/A (derive from legs) | Check leg readiness | N/A | **SKIP** (derive, don't fetch) |
| 9 | `sell_ce_entered` | Leg Status | 4 | get_leg('sell_ce') | is not None | fallback boolean | **MEDIUM** (optional) |
| 10 | `lot_size` | Config Value | 4 | N/A (Config.LOTS) | Config.LOTS or state | N/A | **SKIP** (config, not state) |

---

## SECTION C: REPLACEMENT RULES & STRATEGY

### C.1 Core Migration Rules

**Rule 1: Prefer TradeLegManager for All Leg Keys**
- Pattern: Use `self.trade_leg_manager.get_leg('leg_name')` for any key matching `{leg}_*`
- Example: `sell_ce_token` → `self.trade_leg_manager.get_leg('sell_ce').token`
- Applies to: tokens, strikes, prices, status flags for sell_ce, sell_pe, buy_ce, buy_pe

**Rule 2: Explicit None-Check Pattern for Leg Access**
```python
# For MANDATORY legs (tokens, required metadata):
leg = self.trade_leg_manager.get_leg('sell_ce')
if leg is None:
    logger.error("Missing mandatory leg: sell_ce")
    raise RuntimeError("Missing mandatory leg: sell_ce")
tok = leg.token

# For OPTIONAL legs (status checks, optional metadata):
leg = self.trade_leg_manager.get_leg('buy_ce')
if leg is not None:
    status = leg.is_entered()  # or check another field
else:
    status = False  # Fallback
```

**Rule 3: TradeLegV1 Field Mapping**
- `leg.token` → Original token identifier
- `leg.quantity` → Position quantity
- `leg.entry_price` → Entry price
- Other metadata → Fallback to legacy state.get() with explicit comment

**Rule 4: Phase & Non-Leg Keys (NO MIGRATE)**
- Keys: `phase`, `phase0_done`, `phase1_done`, `trade_state`, `initialized`
- Action: **Keep as-is** (already wrapped in StrategyState with proper validation)
- Rationale: These are system-level flags, not leg-specific; StrategyState handles them safely

**Rule 5: Config/Metadata Keys (NO MIGRATE)**
- Keys: `lot_size`, `atm_strike`, `expiry`
- Action: **Keep as-is** or replace with Config lookup
- Rationale: These are not part of TradeLegV1; they're separate configuration

**Rule 6: TODO/Comment Pattern**
```python
# For each migration, add comment ABOVE the replacement:
# TODO MIGRATE: 'state_key' from legacy state.get() to type-safe accessor [mandatory|optional]

# For uncertain mappings:
# TODO REVIEW: confirm mapping of 'state_key' to TradeLegV1 field
```

**Rule 7: Preserve Variable Names**
- Original: `tok = self.state.get('sell_ce_token')`
- Migrated: `tok = leg.token` (keep variable name `tok`)
- Benefit: Minimal diffs, easier code review, no downstream refactoring

### C.2 Mandatory vs Optional Handling

**Mandatory Keys** (RAISE if missing):
- `sell_ce_token`, `sell_pe_token`, `buy_ce_token`, `buy_pe_token` (must exist for active legs)
- `sell_ce_strike`, `sell_pe_strike`, `buy_ce_strike`, `buy_pe_strike` (required metadata)
- Action: Check `if leg is None:`, log error, raise `RuntimeError("Missing mandatory leg: ...")`

**Optional Keys** (LOG warning, CONTINUE):
- `sell_ce_entry_price`, `buy_ce_entry_price`, leg status flags (_entered, _exited, _leg_ready)
- `_phase1_attempt_count`, `hard_exit_blocked` (internal flags)
- Action: Check `if leg is not None:`, use value; else use None or default

**No-Migrate Keys** (KEEP as-is):
- `phase`, `phase1_done`, `trade_state`, `lot_size`, `atm_strike`, `expiry`
- Rationale: Already safe, config values, or system-level flags

---

## SECTION D: PATCH GENERATION SCRIPT

### D.1 Script: generate_migration_patches.py

**Location:** `generate_migration_patches.py` (in same directory as strategy/engine.py)

**Purpose:**
- Scans strategy/engine.py for all `self.state.get('KEY', ...)` patterns
- For each migrable occurrence, generates a git-style unified diff patch
- Marks non-migrable keys for manual review
- Produces migration_suggestions.csv summary table

**Key Features:**
- ✅ Does NOT auto-apply patches (safe, requires manual review)
- ✅ Generates individual patch files (one per unique occurrence context)
- ✅ Adds TODO comments for traceability
- ✅ Detects mandatory vs optional and generates appropriate checks
- ✅ Skips non-leg keys automatically
- ✅ Produces CSV summary with recommendations

**Output Files:**
- `patch_migrate_001.diff`, `patch_migrate_002.diff`, ... (one per migrable key)
- `migration_suggestions.csv` (summary table: line_num, state_key, patch_file, mapping_status, recommendation)

---

## SECTION E: USAGE GUIDE

### Step 1: Generate Migration Patches

**Command:**
```bash
python generate_migration_patches.py
```

**Expected Output:**
```
Found 125 occurrences of self.state.get() in strategy/engine.py

[001] Line 177: 'trade_state' -> patch_migrate_001.diff
[KEEP] Line 270: 'initialized' (NO_AUTO_PATCH non-leg, type=flag)
[KEEP] Line 280: 'trade_state' (NO_AUTO_PATCH non-leg, type=struct)
[SKIP] Line 399: 'phase' (NO_AUTO_PATCH non-leg, type=phase)
[002] Line 441: 'last_modify_time' -> patch_migrate_002.diff
...
✅ MIGRATION PLAN GENERATED
Total occurrences found:  125
Patches generated:        45-60
Kept as-is (safe):        50-65
Manual review needed:     5-10
```

### Step 2: Review Migration Summary

**Command:**
```bash
# View the CSV summary
cat migration_suggestions.csv | column -t -s',' | head -30

# Example output:
# line_num state_key           patch_file              mapping_status                      recommendation
# 177      trade_state         (NO_PATCH)              NO_AUTO_PATCH (non-leg, struct)     KEEP_AS_IS
# 270      initialized         (NO_PATCH)              NO_AUTO_PATCH (non-leg, type=flag)  KEEP_AS_IS
# 441      (dynamic)           patch_migrate_001.diff  TradeLegManager('sell_ce').token    REVIEW_AND_APPLY
```

### Step 3: Inspect Individual Patches

**Command:**
```bash
# View a specific patch before applying
cat patch_migrate_001.diff

# Expected output:
# --- a/strategy/engine.py
# +++ b/strategy/engine.py
# @@ -... @@
# # TODO MIGRATE: 'sell_ce_token' [mandatory]
# leg = self.trade_leg_manager.get_leg('sell_ce')
# if leg is None:
#     logger.error("Missing mandatory leg: sell_ce")
#     raise RuntimeError("Missing mandatory leg: sell_ce")
# tok = leg.token
```

### Step 4: Validate Patch Syntax

**Command:**
```bash
# Dry-run: check if patch can be applied without errors
git apply --check patch_migrate_001.diff

# If OK (exit code 0), proceed to apply
```

### Step 5: Apply Patch and Test

**Command:**
```bash
# Apply the patch
git apply patch_migrate_001.diff

# Verify syntax
python -m py_compile strategy/engine.py

# Run unit tests
python -m pytest test_state_validation.py -v

# Stage and commit
git add strategy/engine.py
git commit -m "Migrate state.get('sell_ce_token') -> type-safe TradeLegManager accessor (patch_migrate_001)"
```

### Step 6: Repeat for Batches of Patches

**Recommended Batch Order:**
1. **Batch 1:** OPTIONAL leg status keys (sell_ce_leg_ready, buy_ce_entered, etc.)
2. **Batch 2:** LEG TOKENS (sell_ce_token, buy_pe_token, etc.) — MANDATORY
3. **Batch 3:** METADATA keys (sell_ce_strike, buy_ce_entry_price, etc.)

**Example Batch Workflow:**
```bash
# Apply 3 related patches in sequence
for patch in patch_migrate_001.diff patch_migrate_002.diff patch_migrate_003.diff; do
    echo "Applying $patch..."
    git apply --check "$patch" || exit 1
    git apply "$patch"
    git add strategy/engine.py
    git commit -m "Migrate state.get() to type-safe accessor ($(basename $patch))"
    python -m pytest test_state_validation.py --tb=short || exit 1
done
```

### Step 7: Rollback if Issues Arise

**Command:**
```bash
# View recent commits
git log --oneline -5

# Revert last commit
git reset HEAD~1

# Restore file to pre-patch state
git checkout strategy/engine.py

# Or full reset to master
git reset --hard master
```

---

## SECTION F: REVIEWER CHECKLIST

### Pre-Application Checklist (For Each Patch)

- [ ] **Patch Syntax:** `git apply --check patch_migrate_NNN.diff` → exit code 0
- [ ] **Field name exists in TradeLegV1:**
  ```bash
  python3 -c "from contract import TradeLegV1; import inspect; print(inspect.signature(TradeLegV1.__init__))"
  ```
  Confirm field exists (token, quantity, entry_price, etc.)
- [ ] **Semantics match original logic:**
  - Original: `tok = self.state.get('sell_ce_token')` → New: `tok = leg.token`
  - Logic unchanged, just source of truth changes
- [ ] **None-check correct for context:**
  - Mandatory legs: `if leg is None: raise RuntimeError(...)`
  - Optional legs: `if leg: use_leg() else: use_default()`
- [ ] **Variable names preserved:**
  - All downstream code expects same variable names (e.g., `tok_ce`, `ref`, `strike`)
- [ ] **Context lines match file:**
  - First 3 lines of diff are exactly as they appear in strategy/engine.py at that line number

### Post-Application Checklist

- [ ] **Git status clean:**
  ```bash
  git status  # Should show only strategy/engine.py modified
  ```
- [ ] **Syntax error-free:**
  ```bash
  python -m py_compile strategy/engine.py
  python -m flake8 strategy/engine.py --count  # Optional but recommended
  ```
- [ ] **Unit tests pass:**
  ```bash
  python -m pytest test_state_validation.py::TestStateValidation -v
  python verify_state_migration_fix.py
  ```
- [ ] **Verification script succeeds:**
  ```bash
  python verify_state_migration_fix.py
  # Expected: "Results: 5/5 criteria passed — SUCCESS"
  ```
- [ ] **Grep confirms fewer unsafe calls:**
  ```bash
  grep -c "self\.state\.get('sell_ce_token')" strategy/engine.py
  # Should show 0 after replacement
  ```
- [ ] **Commit message descriptive:**
  ```bash
  git log -1 --oneline
  # Example: "Migrate state.get('sell_ce_token') -> TradeLegManager.get_leg().token (patch_001)"
  ```

### Validation Examples

**Before Patch:**
```python
# Line 1696
tok_ce = self.state.get('sell_ce_token')  # Unsafe dict access
```

**After Patch (with passing checklist):**
```python
# Line 1695
# TODO MIGRATE: 'sell_ce_token' from legacy state.get() to type-safe accessor [mandatory]
leg = self.trade_leg_manager.get_leg('sell_ce')
if leg is None:
    logger.error("Missing mandatory leg: sell_ce")
    raise RuntimeError("Missing mandatory leg: sell_ce")
tok_ce = leg.token  # Type-safe access via TradeLegV1
```

---

## SECTION G: SUMMARY & RECOMMENDATIONS

### Current State
- ✅ 125+ unsafe `state.get()` calls identified
- ✅ 37 unique state keys categorized
- ✅ Top 10 keys mapped to safe accessors
- ✅ Patch generation script ready
- ✅ Replacement rules documented
- ✅ No patches applied yet (safe state)

### Recommended Phased Approach

**Phase 1 (LOW RISK - Optional Leg Status Keys)**
- Patches for: `buy_ce_leg_ready`, `sell_pe_entered`, `buy_ce_entered`, `sell_ce_exited`
- Count: ~10-15 patches
- Risk: Low (optional checks with fallbacks)
- Duration: 1-2 hours

**Phase 2 (MEDIUM RISK - Mandatory Leg Tokens)**
- Patches for: `sell_ce_token`, `buy_pe_token`, `sell_pe_token`, `buy_ce_token`
- Count: ~4-8 patches
- Risk: Medium (mandatory checks; raise if missing)
- Duration: 2-3 hours
- Precaution: Add explicit test for "leg missing" error path

**Phase 3 (MEDIUM RISK - Metadata Keys)**
- Patches for: `sell_ce_strike`, `buy_ce_entry_price`, `sell_pe_ref_premium`, etc.
- Count: ~15-20 patches
- Risk: Medium (fallback to state if not in leg)
- Duration: 3-4 hours

**Phase 4 (SKIPPED - Config/Phase Keys)**
- No patches: `phase`, `phase1_done`, `lot_size`, etc.
- Rationale: Already safe via StrategyState wrapper or config lookup

### Success Criteria

✅ **After All Patches Applied:**
1. `grep "self\.state\.get(" strategy/engine.py` returns only ~10 occurrences (safe/non-migrable keys)
2. All 125+ original calls replaced or marked with explanation
3. Unit tests 100% pass rate
4. Verification script reports 5/5 criteria passed
5. Code review confirms type-safety improvements
6. No performance regressions

### Next Steps

1. **DO NOT AUTO-APPLY PATCHES** — Review before each application
2. **Run:** `python generate_migration_patches.py`
3. **Review:** `cat migration_suggestions.csv`
4. **Test:** Apply first patch, run tests, confirm all pass
5. **Iterate:** Proceed in batches (Phase 1 → Phase 2 → Phase 3)
6. **Create PR** when all phases complete, with detailed description

---

**Document Status:** ✅ COMPLETE & READY FOR REVIEW

**Files Included:**
1. `MIGRATION_PLAN.md` — Detailed migration strategy (this document)
2. `generate_migration_patches.py` — Automated patch generator script
3. Patches (`patch_migrate_NNN.diff`) — Generated on-demand (not yet created)
4. `migration_suggestions.csv` — Summary table (generated on-demand)

**Permission Status:** ✅ All documentation complete. NO PATCHES HAVE BEEN APPLIED. Awaiting user review and confirmation before proceeding.
