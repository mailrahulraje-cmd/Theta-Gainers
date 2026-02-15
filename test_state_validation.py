#!/usr/bin/env python3
"""
Unit Tests for State Schema Validation and Type-Safe Access
Tests cover:
1. State schema validation
2. Checksum computation and verification
3. Version migration
4. Type-safe accessor methods
"""

import unittest
import json
import tempfile
import os
from datetime import datetime

# Add parent directory to path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state_schema import (
    validate_state_schema,
    compute_state_checksum,
    verify_state_checksum,
    ensure_state_valid,
    migrate_state_v1_to_v2,
    validate_and_migrate_state,
    get_leg_safe,
    get_leg_token,
    get_leg_state,
    is_leg_entered,
    has_any_entered_leg,
    STATE_VERSION,
    REQUIRED_STATE_FIELDS
)


class TestStateSchemaValidation(unittest.TestCase):
    """Test state schema validation"""
    
    def test_validate_empty_state(self):
        """Empty state should fail validation"""
        valid, msg = validate_state_schema({})
        self.assertFalse(valid)
        self.assertIn("empty", msg.lower())
    
    def test_validate_missing_required_fields(self):
        """State missing required fields should fail"""
        partial_state = {"_version": "2.0"}
        valid, msg = validate_state_schema(partial_state)
        self.assertFalse(valid)
        self.assertIn("missing", msg.lower())
    
    def test_validate_complete_state(self):
        """Complete valid state should pass"""
        valid_state = {
            "_version": "2.0",
            "_checksum": "abc123",
            "phase": "INIT",
            "trade_state": {"sell_ce": "IDLE", "sell_pe": "IDLE", "buy_ce": "IDLE", "buy_pe": "IDLE"},
            "legs": {"sell_ce": {}, "sell_pe": {}, "buy_ce": {}, "buy_pe": {}}
        }
        valid, msg = validate_state_schema(valid_state)
        self.assertTrue(valid)
    
    def test_validate_wrong_field_types(self):
        """Wrong field types should fail"""
        bad_state = {
            "_version": "2.0",
            "_checksum": "abc123",
            "phase": 123,  # Should be string
            "trade_state": {},
            "legs": {}
        }
        valid, msg = validate_state_schema(bad_state)
        self.assertFalse(valid)
        self.assertIn("phase must be string", msg)


class TestChecksumComputation(unittest.TestCase):
    """Test checksum computation and verification"""
    
    def setUp(self):
        """Create test state"""
        self.test_state = {
            "_version": "2.0",
            "phase": "INIT",
            "trade_state": {"sell_ce": "IDLE", "sell_pe": "IDLE", "buy_ce": "IDLE", "buy_pe": "IDLE"},
            "legs": {"sell_ce": {}, "sell_pe": {}, "buy_ce": {}, "buy_pe": {}}
        }
    
    def test_checksum_computed(self):
        """Checksum should be computed without _checksum field"""
        checksum = compute_state_checksum(self.test_state)
        self.assertEqual(len(checksum), 64)  # SHA256 is 64 hex chars
        self.assertTrue(all(c in '0123456789abcdef' for c in checksum))
    
    def test_checksum_consistent(self):
        """Same state should always produce same checksum"""
        check1 = compute_state_checksum(self.test_state)
        check2 = compute_state_checksum(self.test_state)
        self.assertEqual(check1, check2)
    
    def test_checksum_changes_on_data_change(self):
        """Checksum should change if data changes"""
        check1 = compute_state_checksum(self.test_state)
        self.test_state["phase"] = "ENTRY_ALLOWED"
        check2 = compute_state_checksum(self.test_state)
        self.assertNotEqual(check1, check2)
    
    def test_checksum_verification_passes(self):
        """Correct checksum should verify"""
        self.test_state["_checksum"] = compute_state_checksum(self.test_state)
        valid, msg = verify_state_checksum(self.test_state)
        self.assertTrue(valid)
    
    def test_checksum_verification_fails_on_tampering(self):
        """Corrupted data should fail checksum verification"""
        self.test_state["_checksum"] = compute_state_checksum(self.test_state)
        # Tamper with data
        self.test_state["phase"] = "CORRUPTED"
        valid, msg = verify_state_checksum(self.test_state)
        self.assertFalse(valid)
        self.assertIn("mismatch", msg.lower())


class TestStateMigration(unittest.TestCase):
    """Test state migration from v1.0 to v2.0"""
    
    def test_migrate_legacy_state(self):
        """Legacy v1.0 state should migrate to v2.0"""
        legacy_state = {
            "sell_ce_token": "12345",
            "sell_ce_strike": 45000,
            "sell_ce_entered": True,
            "sell_ce_symbol": "NIFTY45000CE",
            "sell_pe_token": "12346",
            "sell_pe_entered": False,
            "buy_ce_token": "12347",
            "buy_ce_entered": True,
            "buy_pe_token": "12348",
            "buy_pe_entered": False,
        }
        
        migrated = migrate_state_v1_to_v2(legacy_state)
        
        # Check version
        self.assertEqual(migrated["_version"], STATE_VERSION)
        
        # Check structure
        self.assertIn("legs", migrated)
        self.assertIn("trade_state", migrated)
        self.assertIn("_checksum", migrated)
        
        # Check leg data preserved
        self.assertEqual(migrated["legs"]["sell_ce"]["token"], "12345")
        self.assertEqual(migrated["trade_state"]["sell_ce"], "ENTERED")
        self.assertEqual(migrated["trade_state"]["sell_pe"], "IDLE")
    
    def test_full_validation_pipeline(self):
        """Full pipeline should handle old and new states"""
        legacy_state = {
            "sell_ce_token": "12345",
            "sell_ce_entered": True,
        }
        
        validated, msg = validate_and_migrate_state(legacy_state)
        
        # Should be migrated
        self.assertEqual(validated["_version"], STATE_VERSION)
        self.assertIn("legs", validated)
        self.assertIn("_checksum", validated)


class TestEnsureStateValid(unittest.TestCase):
    """Test state auto-fixing"""
    
    def test_add_missing_version(self):
        """Missing version should be added"""
        state = {"phase": "INIT"}
        fixed = ensure_state_valid(state)
        self.assertEqual(fixed["_version"], STATE_VERSION)
    
    def test_add_missing_checksum(self):
        """Missing checksum should be computed"""
        state = {"_version": "2.0", "phase": "INIT"}
        fixed = ensure_state_valid(state)
        self.assertIn("_checksum", fixed)
        self.assertEqual(len(fixed["_checksum"]), 64)
    
    def test_add_basic_structure(self):
        """Missing structures should be added"""
        state = {}
        fixed = ensure_state_valid(state)
        self.assertIn("phase", fixed)
        self.assertIn("trade_state", fixed)
        self.assertIn("legs", fixed)
        self.assertIn("_version", fixed)
        self.assertIn("_checksum", fixed)


class TestTypeSafeAccessors(unittest.TestCase):
    """Test type-safe accessor methods"""
    
    def setUp(self):
        """Create test state"""
        self.test_state = {
            "_version": "2.0",
            "_checksum": "",
            "phase": "INIT",
            "trade_state": {
                "sell_ce": "ENTERED",
                "sell_pe": "IDLE",
                "buy_ce": "READY",
                "buy_pe": "IDLE"
            },
            "legs": {
                "sell_ce": {"token": "12345", "entered": True},
                "sell_pe": {"token": None, "entered": False},
                "buy_ce": {"token": "12347", "entered": False},
                "buy_pe": {"token": None, "entered": False}
            }
        }
    
    def test_get_leg_safe(self):
        """Should retrieve leg data safely"""
        leg = get_leg_safe(self.test_state, "sell_ce")
        self.assertIsNotNone(leg)
        self.assertEqual(leg.get("token"), "12345")
    
    def test_get_leg_safe_missing(self):
        """Should return None for missing leg"""
        leg = get_leg_safe(self.test_state, "invalid_leg")
        self.assertIsNone(leg)
    
    def test_get_leg_token(self):
        """Should extract token safely"""
        token = get_leg_token(self.test_state, "sell_ce")
        self.assertEqual(token, "12345")
    
    def test_get_leg_token_missing(self):
        """Should return None for leg without token"""
        token = get_leg_token(self.test_state, "sell_pe")
        self.assertIsNone(token)
    
    def test_get_leg_state(self):
        """Should get leg state"""
        state = get_leg_state(self.test_state, "sell_ce")
        self.assertEqual(state, "ENTERED")
    
    def test_get_leg_state_default(self):
        """Should default to IDLE for unknown legs"""
        state = get_leg_state(self.test_state, "invalid_leg")
        self.assertEqual(state, "IDLE")
    
    def test_is_leg_entered(self):
        """Should check if leg is entered"""
        self.assertTrue(is_leg_entered(self.test_state, "sell_ce"))
        self.assertFalse(is_leg_entered(self.test_state, "sell_pe"))
    
    def test_has_any_entered_leg(self):
        """Should detect if any leg is entered"""
        self.assertTrue(has_any_entered_leg(self.test_state))
        
        # All IDLE
        self.test_state["trade_state"] = {
            "sell_ce": "IDLE", "sell_pe": "IDLE",
            "buy_ce": "IDLE", "buy_pe": "IDLE"
        }
        self.assertFalse(has_any_entered_leg(self.test_state))


class TestStrategyStateIntegration(unittest.TestCase):
    """Integration tests with StrategyState"""
    
    def test_state_loads_with_validation(self):
        """StrategyState should validate on load"""
        from core.state import StrategyState
        
        # Create temp state file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            state_file = f.name
            # Write valid state
            valid_state = {
                "_version": "2.0",
                "_checksum": "",
                "phase": "INIT",
                "trade_state": {"sell_ce": "IDLE", "sell_pe": "IDLE", "buy_ce": "IDLE", "buy_pe": "IDLE"},
                "legs": {"sell_ce": {}, "sell_pe": {}, "buy_ce": {}, "buy_pe": {}}
            }
            # Add checksum
            valid_state["_checksum"] = compute_state_checksum(valid_state)
            json.dump(valid_state, f)
        
        try:
            # Load state
            state = StrategyState(state_file)
            
            # Should have version
            self.assertEqual(state.state.get("_version"), STATE_VERSION)
            
            # Should have checksum
            self.assertIn("_checksum", state.state)
        finally:
            # Cleanup
            if os.path.exists(state_file):
                os.unlink(state_file)
    
    def test_type_safe_accessors_on_state(self):
        """StrategyState should provide type-safe accessors"""
        from core.state import StrategyState
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            state_file = f.name
            valid_state = {
                "_version": "2.0",
                "_checksum": "",
                "phase": "INIT",
                "trade_state": {"sell_ce": "ENTERED", "sell_pe": "IDLE", "buy_ce": "IDLE", "buy_pe": "IDLE"},
                "legs": {
                    "sell_ce": {"token": "TEST123", "entered": True},
                    "sell_pe": {}, "buy_ce": {}, "buy_pe": {}
                }
            }
            valid_state["_checksum"] = compute_state_checksum(valid_state)
            json.dump(valid_state, f)
        
        try:
            state = StrategyState(state_file)
            
            # Test accessors
            self.assertTrue(state.is_leg_entered("sell_ce"))
            self.assertFalse(state.is_leg_entered("sell_pe"))
            self.assertEqual(state.get_leg_token("sell_ce"), "TEST123")
            self.assertEqual(state.get_leg_state("sell_ce"), "ENTERED")
            self.assertTrue(state.has_any_entered_leg())
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


if __name__ == '__main__':
    unittest.main()
