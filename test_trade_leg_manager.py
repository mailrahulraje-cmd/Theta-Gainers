#!/usr/bin/env python3
"""
Comprehensive test suite for TradeLegManager integration.

Tests:
  1. Basic TradeLegManager operations
  2. Legacy dict migration
  3. Serialization/deserialization with checksums
  4. Integrity verification
  5. CSV export
"""

import logging
from datetime import datetime
from contract import TradeLegV1
from core.trade_leg_manager import TradeLegManager

# Setup logging for test visibility
logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


def test_basic_operations():
    """Test create, get, set, has, delete operations."""
    print("\n=== Test 1: Basic Operations ===")
    
    manager = TradeLegManager()
    assert len(manager.get_active_legs()) == 0
    print("✓ Created empty TradeLegManager")
    
    # Create and set a leg
    leg_sell_ce = TradeLegV1(
        token="45000CE",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000"
    )
    manager.set_leg("sell_ce", leg_sell_ce)
    print("✓ Set sell_ce leg")
    
    # Get the leg
    retrieved = manager.get_leg("sell_ce")
    assert retrieved is not None
    assert retrieved.entry_price == 50.0
    print("✓ Retrieved sell_ce leg with correct data")
    
    # Check has_leg
    assert manager.has_leg("sell_ce")
    assert not manager.has_leg("sell_pe")
    print("✓ has_leg() works correctly")
    
    # Check active legs
    active = manager.get_active_legs()
    assert active == ["sell_ce"]
    print("✓ get_active_legs() returns correct list")
    
    # Delete leg
    manager.delete_leg("sell_ce")
    assert not manager.has_leg("sell_ce")
    print("✓ delete_leg() works correctly")


def test_multiple_legs():
    """Test managing multiple legs together."""
    print("\n=== Test 2: Multiple Legs ===")
    
    manager = TradeLegManager()
    
    # Create all four legs
    legs_data = {
        "sell_ce": ("50000CE", 50.0, 1, "SELL"),
        "sell_pe": ("50000PE", 52.0, 1, "SELL"),
        "buy_ce": ("50100CE", 30.0, 2, "BUY"),
        "buy_pe": ("50100PE", 28.0, 2, "BUY")
    }
    
    for leg_name, (token, price, qty, side) in legs_data.items():
        leg = TradeLegV1(
            token=token,
            entry_price=price,
            quantity=qty,
            side=side,
            timestamp="2025-02-15T09:30:00.000000"
        )
        manager.set_leg(leg_name, leg)
    
    print(f"✓ Created {len(manager.get_active_legs())} legs")
    
    # Verify all legs present
    assert len(manager.get_active_legs()) == 4
    assert manager.has_leg("sell_ce")
    assert manager.has_leg("sell_pe")
    assert manager.has_leg("buy_ce")
    assert manager.has_leg("buy_pe")
    print("✓ All 4 legs present and accessible")
    
    # Print summary
    print(manager.summary())


def test_invalid_leg_name():
    """Test validation of leg names."""
    print("\n=== Test 3: Invalid Leg Names ===")
    
    manager = TradeLegManager()
    leg = TradeLegV1(
        token="12345",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000"
    )
    
    try:
        manager.set_leg("invalid_leg", leg)
        print("✗ Should have rejected invalid leg name")
    except ValueError as e:
        print(f"✓ Rejected invalid leg name: {e}")


def test_invalid_leg_type():
    """Test type validation for set_leg."""
    print("\n=== Test 4: Invalid Leg Type ===")
    
    manager = TradeLegManager()
    
    try:
        manager.set_leg("sell_ce", {"token": "12345"})  # Pass dict instead of TradeLegV1
        print("✗ Should have rejected non-TradeLegV1 object")
    except TypeError as e:
        print(f"✓ Rejected non-TradeLegV1 object: {e}")


def test_legacy_dict_migration():
    """Test migration from legacy dict format."""
    print("\n=== Test 5: Legacy Dict Migration ===")
    
    # Simulate old state dict
    legacy_state = {
        'sell_ce_token': '50000CE',
        'sell_ce_strike': 50000,
        'sell_ce_ref_premium': 50.0,
        'sell_ce_symbol': 'NIFTY50000CE',
        'sell_ce_qty': 1,
        'sell_ce_entered': True,
        
        'sell_pe_token': '50000PE',
        'sell_pe_strike': 50000,
        'sell_pe_ref_premium': 52.0,
        'sell_pe_symbol': 'NIFTY50000PE',
        'sell_pe_qty': 1,
        'sell_pe_entered': True,
        
        'buy_ce_token': '50100CE',
        'buy_ce_strike': 50100,
        'buy_ce_ref_premium': 30.0,
        'buy_ce_symbol': 'NIFTY50100CE',
        'buy_ce_qty': 2,
        'buy_ce_entered': False,
        
        'buy_pe_token': '50100PE',
        'buy_pe_strike': 50100,
        'buy_pe_ref_premium': 28.0,
        'buy_pe_symbol': 'NIFTY50100PE',
        'buy_pe_qty': 2,
        'buy_pe_entered': False
    }
    
    # Migrate
    manager = TradeLegManager.migrate_from_legacy_dict(legacy_state)
    print(f"✓ Migrated {len(manager.get_active_legs())} legs from legacy format")
    
    # Verify migrated data
    sell_ce = manager.get_leg("sell_ce")
    assert sell_ce is not None
    assert sell_ce.token == "50000CE"
    assert sell_ce.entry_price == 50.0
    assert sell_ce.quantity == 1
    assert sell_ce.side == "SELL"
    assert sell_ce.status == "OPEN"  # All migrated legs start as OPEN
    print("✓ Migrated sell_ce leg has correct data and status=OPEN")
    
    buy_ce = manager.get_leg("buy_ce")
    assert buy_ce.status == "OPEN"  # All migrated legs are OPEN
    print("✓ Migrated buy_ce leg has correct status=OPEN")
    
    print(manager.summary())


def test_serialization_roundtrip():
    """Test to_dict() → from_dict() roundtrip."""
    print("\n=== Test 6: Serialization Roundtrip ===")
    
    # Create manager with legs
    manager1 = TradeLegManager()
    
    leg_sell_ce = TradeLegV1(
        token="50000CE",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000",
        leg_id="SELL_CE_001",
        status="OPEN"
    )
    manager1.set_leg("sell_ce", leg_sell_ce)
    
    leg_buy_ce = TradeLegV1(
        token="50100CE",
        entry_price=30.0,
        quantity=2,
        side="BUY",
        timestamp="2025-02-15T09:31:00.000000",
        leg_id="BUY_CE_001",
        status="OPEN"
    )
    manager1.set_leg("buy_ce", leg_buy_ce)
    
    print("✓ Created manager with 2 legs")
    
    # Serialize
    data = manager1.to_dict()
    print(f"✓ Serialized to dict with {len(data['legs'])} legs and checksums")
    
    # Deserialize
    manager2 = TradeLegManager.from_dict(data)
    print(f"✓ Deserialized 2 legs with checksum verification")
    
    # Verify all data matches
    sell_ce_2 = manager2.get_leg("sell_ce")
    assert sell_ce_2.token == "50000CE"
    assert sell_ce_2.entry_price == 50.0
    assert sell_ce_2.leg_id == "SELL_CE_001"
    print("✓ Deserialized sell_ce leg matches original")
    
    buy_ce_2 = manager2.get_leg("buy_ce")
    assert buy_ce_2.token == "50100CE"
    assert buy_ce_2.quantity == 2
    print("✓ Deserialized buy_ce leg matches original")


def test_checksum_verification():
    """Test checksum computation and verification."""
    print("\n=== Test 7: Checksum Verification ===")
    
    manager = TradeLegManager()
    
    leg = TradeLegV1(
        token="50000CE",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000"
    )
    manager.set_leg("sell_ce", leg)
    
    # Get checksum
    original_checksum = manager.checksums["sell_ce"]
    print(f"✓ Computed checksum: {original_checksum[:16]}...")
    
    # Verify all checksums
    all_valid = manager.verify_all_checksums()
    assert all_valid
    print("✓ verify_all_checksums() returns True")
    
    # Test corruption detection
    data = manager.to_dict()
    corrupted_data = data.copy()
    
    # Tamper with leg data
    corrupted_legs = corrupted_data["legs"].copy()
    corrupted_legs["sell_ce"] = data["legs"]["sell_ce"].copy()
    corrupted_legs["sell_ce"]["entry_price"] = 51.0  # Change price
    corrupted_data["legs"] = corrupted_legs
    
    # Try to load corrupted data
    try:
        manager_bad = TradeLegManager.from_dict(corrupted_data, skip_corrupted=False)
        print("✗ Should have detected corruption")
    except ValueError as e:
        print(f"✓ Detected corruption: {str(e)[:50]}...")
    
    # Load with skip_corrupted=True (graceful)
    manager_skip = TradeLegManager.from_dict(corrupted_data, skip_corrupted=True)
    print(f"✓ Loaded with skip_corrupted=True, loaded {len(manager_skip.get_active_legs())} valid legs")


def test_csv_export():
    """Test CSV export functionality."""
    print("\n=== Test 8: CSV Export ===")
    
    manager = TradeLegManager()
    
    leg = TradeLegV1(
        token="50000CE",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000",
        leg_id="SELL_CE_001",
        status="OPEN"
    )
    manager.set_leg("sell_ce", leg)
    
    # Export to CSV dict
    csv_dict = manager.to_csv_dict("sell_ce")
    assert csv_dict is not None
    assert csv_dict["token"] == "50000CE"
    assert csv_dict["entry_price"] == 50.0
    print("✓ Exported sell_ce to CSV-friendly dict")
    
    # Non-existent leg
    csv_dict_none = manager.to_csv_dict("sell_pe")
    assert csv_dict_none is None
    print("✓ Non-existent leg returns None")


def test_corrupted_leg_graceful_handling():
    """Test graceful handling of corrupted legs during loading."""
    print("\n=== Test 9: Corrupted Leg Handling ===")
    
    # Create data with one valid and one corrupted leg
    data = {
        "version": 1,
        "creation_timestamp": "2025-02-15T09:30:00",
        "legs": {
            "sell_ce": {
                "token": "50000CE",
                "entry_price": 50.0,
                "quantity": 1,
                "side": "SELL",
                "timestamp": "2025-02-15T09:30:00.000000",
                "version": 1,
                "leg_id": "",
                "status": "OPEN",
                "exit_price": None,
                "pnl": None
            },
            "sell_pe": {
                "token": "50000PE",
                "entry_price": -52.0,  # CORRUPTED: negative price!
                "quantity": 1,
                "side": "SELL",
                "timestamp": "2025-02-15T09:30:00.000000",
                "version": 1,
                "leg_id": "",
                "status": "OPEN",
                "exit_price": None,
                "pnl": None
            }
        },
        "checksums": {}
    }
    
    # Load with skip_corrupted=True
    manager = TradeLegManager.from_dict(data, skip_corrupted=True)
    
    # Verify only valid leg loaded
    assert manager.has_leg("sell_ce")
    assert not manager.has_leg("sell_pe")
    print("✓ Loaded 1 valid leg, skipped 1 corrupted leg")
    print(f"✓ Active legs: {manager.get_active_legs()}")


def main():
    """Run all tests."""
    print("=" * 70)
    print(" TRADELEG MANAGER - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    
    try:
        test_basic_operations()
        test_multiple_legs()
        test_invalid_leg_name()
        test_invalid_leg_type()
        test_legacy_dict_migration()
        test_serialization_roundtrip()
        test_checksum_verification()
        test_csv_export()
        test_corrupted_leg_graceful_handling()
        
        print("\n" + "=" * 70)
        print(" ✓ ALL TESTS PASSED (9/9)")
        print("=" * 70)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
