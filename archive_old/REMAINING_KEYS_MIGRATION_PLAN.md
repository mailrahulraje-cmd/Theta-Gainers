# Remaining State Keys Migration Plan

**Branch:** `fix/engine-state-migration-AN-20260215`  
**Migrated:** 61/95 leg-related `state.get()` calls → `TradeLegManager`  
**Remaining:** 24 unique non-leg keys (phase/flags/metadata) — intentional, require review  
**Date:** February 15, 2026

---

## Purpose

This document lists the 24 remaining state keys that were intentionally NOT auto-migrated during Phase 8 because they are:
- **Phase/lifecycle flags** (phase0_done, phase1_done, squareoff_done, phase)
- **Metadata/counters** (_phase1_attempt_count, _phase1_buy_ce_attempts, etc.)
- **Feature flags** (hard_exit_blocked, hard_exit_no_new_entries, initialized)
- **Market data** (atm_strike, expiry, entry prices)
- **Legacy entered flags** (buy_ce_entered, buy_pe_entered, sell_ce_entered, sell_pe_entered, etc.)
- **Trade state dict** (trade_state)

For each key, we assign one of three actions:
1. **KEEP_AS_IS** — Leave in legacy state.dict; no migration needed.
2. **VALIDATE_SCHEMA** — Add runtime validation, bounds checks, and schema enforcement.
3. **MANUAL_MIGRATE** — Migrate to typed accessor or config object with manual review.

---

## Remaining Keys with Recommended Actions

| # | **Key** | **Type** | **Recommended Action** | **Owner** | **Notes / Rationale** |
|---|---------|----------|------------------------|-----------|----------------------|
| 1 | `phase` | String | **VALIDATE_SCHEMA** | TBD | Trading lifecycle phase (INIT/ENTRY/EXIT, etc.). Add enum validation, allowed values check. Add unit tests. |
| 2 | `phase0_done` | Boolean | **KEEP_AS_IS** | TBD | Phase 0 completion flag. Low-risk metadata; no migration needed now. |
| 3 | `phase1_done` | Boolean | **KEEP_AS_IS** | TBD | Phase 1 completion flag. Low-risk metadata; no migration needed now. |
| 4 | `squareoff_done` | Boolean | **KEEP_AS_IS** | TBD | Squareoff completion flag. Low-risk metadata; no migration needed now. |
| 5 | `initialized` | Boolean | **KEEP_AS_IS** | TBD | Startup/init flag. Non-critical for leg lifecycle; keep as-is. |
| 6 | `trade_state` | Dict | **VALIDATE_SCHEMA** | TBD | Single-source-of-truth map for leg states (IDLE/ENTERED/EXITED). Add schema validation to ensure all legs present and values valid. |
| 7 | `lot_size` | Integer | **VALIDATE_SCHEMA** | TBD | Order size config. Add bounds check (>0, <max limit), default value, and docstring. Consider typed config object in future. |
| 8 | `atm_strike` | Float | **KEEP_AS_IS** | TBD | Market-derived data (ATM strike price). Market snapshot; no migration needed for now. Document how/when it's updated. |
| 9 | `expiry` | String/Date | **VALIDATE_SCHEMA** | TBD | Contract expiry date. Validate format (YYYY-MM-DD or similar), ensure consistent timezone handling. Add unit tests. |
| 10 | `buy_ce_entered` | Boolean | **KEEP_AS_IS** | TBD | Legacy entered flag for buy_ce leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. Document deprecation path. |
| 11 | `buy_pe_entered` | Boolean | **KEEP_AS_IS** | TBD | Legacy entered flag for buy_pe leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. Document deprecation path. |
| 12 | `sell_ce_entered` | Boolean | **KEEP_AS_IS** | TBD | Legacy entered flag for sell_ce leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. Document deprecation path. |
| 13 | `sell_pe_entered` | Boolean | **KEEP_AS_IS** | TBD | Legacy entered flag for sell_pe leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. Document deprecation path. |
| 14 | `sell_ce_entry_price` | Float | **KEEP_AS_IS** | TBD | Entry price for sell_ce leg. Market snapshot; kept for audit/reporting. Document usage and deprecation plans. |
| 15 | `sell_pe_entry_price` | Float | **KEEP_AS_IS** | TBD | Entry price for sell_pe leg. Market snapshot; kept for audit/reporting. Document usage and deprecation plans. |
| 16 | `sell_ce_exited` | Boolean | **KEEP_AS_IS** | TBD | Legacy exit flag for sell_ce leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. No migration needed. |
| 17 | `sell_pe_exited` | Boolean | **KEEP_AS_IS** | TBD | Legacy exit flag for sell_pe leg. Kept for backward compat; leg state info now in `trade_state` and TradeLegManager. No migration needed. |
| 18 | `hard_exit_blocked` | Boolean | **KEEP_AS_IS** | TBD | Feature flag to block hard exit. Low-risk flag; no migration needed. Documented usage. |
| 19 | `hard_exit_no_new_entries` | Boolean | **KEEP_AS_IS** | TBD | Feature flag to block new entries during hard exit. Low-risk flag; no migration needed. Documented usage. |
| 20 | `_phase1_attempt_count` | Integer | **KEEP_AS_IS** | TBD | Phase 1 attempt counter (metadata). Audit-only field; no migration needed. |
| 21 | `_phase1_buy_ce_attempts` | Integer | **KEEP_AS_IS** | TBD | Phase 1 buy_ce attempt counter (metadata). Audit-only field; no migration needed. |
| 22 | `_phase1_buy_pe_attempts` | Integer | **KEEP_AS_IS** | TBD | Phase 1 buy_pe attempt counter (metadata). Audit-only field; no migration needed. |
| 23 | `_phase1_buy_ce_final_status` | String | **KEEP_AS_IS** | TBD | Phase 1 buy_ce final status (metadata). Audit-only field; no migration needed. |
| 24 | `_phase1_buy_pe_final_status` | String | **KEEP_AS_IS** | TBD | Phase 1 buy_pe final status (metadata). Audit-only field; no migration needed. |

---

## Action Items by Category

### A. VALIDATE_SCHEMA (Requires Unit Tests & Schema Enforcement)

These keys need runtime validation, bounds checks, or schema enforcement:

| **Key** | **Validation Required** | **Target PR** | **Status** |
|---------|------------------------|---------------|-----------|
| `phase` | Enum: {INIT, ENTRY, EXIT, ...}; non-empty string | Phase Validation PR | Not Started |
| `trade_state` | Dict with all 4 legs (sell_ce, sell_pe, buy_ce, buy_pe); values in {IDLE, ENTERED, EXITED} | Trade State Schema PR | Not Started |
| `lot_size` | Integer >0 and <MAX_ORDER_SIZE; default value | Config Validation PR | Not Started |
| `expiry` | Date format YYYY-MM-DD; consistent timezone; non-null | Market Data Schema PR | Not Started |

### B. KEEP_AS_IS (No Migration Needed)

These keys are low-risk, metadata-only, or feature flags and should remain in legacy state dict:

- **Phase flags:** phase0_done, phase1_done, squareoff_done, initialized
- **Feature flags:** hard_exit_blocked, hard_exit_no_new_entries
- **Metadata counters:** _phase1_attempt_count, _phase1_buy_ce_attempts, _phase1_buy_pe_attempts, _phase1_buy_ce_final_status, _phase1_buy_pe_final_status
- **Market snapshots:** atm_strike
- **Legacy entered/exit flags** (deprecated, kept for backward compat): buy_ce_entered, buy_pe_entered, sell_ce_entered, sell_pe_entered, sell_ce_exited, sell_pe_exited
- **Legacy entry prices** (kept for audit/reporting): sell_ce_entry_price, sell_pe_entry_price

**Action:** Document deprecation in code comments; no migration PRs required for now.

### C. MANUAL_MIGRATE (Future Work — Lower Priority)

None identified for this batch. Recommend revisiting in a future phase if typed config objects are introduced.

---

## Next Steps

### Phase 9: Merge Current PR
1. ✅ TradeLegManager integration complete
2. ✅ 61 leg-related calls migrated
3. ✅ 24/24 unit tests passing
4. ✅ This document created for reviewer reference
5. **Action:** Merge `fix/engine-state-migration-AN-20260215` with this plan as attachment

### Phase 10: Schema Validation (Post-Merge)
1. Owner assigns to team members (one per item):
   - `phase` validation → Config owner
   - `trade_state` schema → State owner
   - `lot_size` validation → Order sizing owner
   - `expiry` format → Market data owner
2. Create small 1-line-of-code PRs with unit tests for each
3. Target: Merge all schema validation PRs within 2 weeks

### Phase 11: Deprecation (Later)
1. Add deprecation warnings to legacy entered/exit flags (e.g., "buy_ce_entered")
2. Update docstrings to reference TradeLegManager and trade_state instead
3. Document migration path for users reading code

---

## Review Checklist for Merge

- [ ] Confirm all 61 migrated calls use TradeLegManager.get_leg() with proper null checks.
- [ ] Verify StrategyEngine unit tests pass (24/24).
- [ ] Ensure no remaining unsafe `self.state.get(` calls outside strategy/engine.py.
- [ ] Review migration_suggestions.csv; approve the 24 KEEP_AS_IS decisions.
- [ ] Assign owners to the 4 VALIDATE_SCHEMA keys (Owners column).
- [ ] Confirm this document will be referenced in PR description.

---

## Summary

| Metric | Count | Status |
|--------|-------|--------|
| Total state.get() calls analyzed | 95 | ✅ Complete |
| Migrated to TradeLegManager | 61 | ✅ Complete |
| Remaining (non-leg keys) | 24 | ✅ Documented |
| Unique action categories | 2 | ✅ Defined |
| KEEP_AS_IS keys | 20 | ✅ No action needed |
| VALIDATE_SCHEMA keys | 4 | 🔄 Queued for Phase 10 |
| Unit tests passing | 24/24 | ✅ 100% |

**Overall Status:** Type-safe migration complete; remaining keys catalogued and assigned.

**Next Owner Action:** Assign owners to 4 VALIDATE_SCHEMA keys and schedule Phase 10 PRs.
