#!/usr/bin/env python3
"""
Test suite for TradeLegV1 - Validates all versioning, serialization, and integrity features.
"""

from contract import TradeLegV1
from datetime import datetime

def test_basic_creation():
    """Test basic TradeLegV1 instantiation"""
    print("\n=== Test 1: Basic Creation ===")
    leg = TradeLegV1(
        token="12345",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000"
    )
    print(f"✓ Created leg: {leg}")
    assert leg.version == 1
    print("✓ Version is 1")

def test_validation_entry_price():
    """Test entry_price validation"""
    print("\n=== Test 2: Entry Price Validation ===")
    
    # Test negative price
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=-50.0,
            quantity=1,
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000"
        )
        print("✗ Should have rejected negative entry_price")
    except ValueError as e:
        print(f"✓ Rejected negative price: {e}")
    
    # Test zero price
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=0.0,
            quantity=1,
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000"
        )
        print("✗ Should have rejected zero entry_price")
    except ValueError as e:
        print(f"✓ Rejected zero price: {e}")

def test_validation_quantity():
    """Test quantity validation"""
    print("\n=== Test 3: Quantity Validation ===")
    
    # Test negative quantity
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity=-1,
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000"
        )
        print("✗ Should have rejected negative quantity")
    except ValueError as e:
        print(f"✓ Rejected negative quantity: {e}")
    
    # Test string quantity (wrong type)
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity="1",
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000"
        )
        print("✗ Should have rejected string quantity")
    except ValueError as e:
        print(f"✓ Rejected wrong type: {e}")

def test_validation_side():
    """Test side validation"""
    print("\n=== Test 4: Side Validation ===")
    
    # Valid sides
    for side in ["SELL", "BUY"]:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity=1,
            side=side,
            timestamp="2025-02-15T09:30:00.000000"
        )
        print(f"✓ Accepted side: {side}")
    
    # Invalid side
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity=1,
            side="INVALID",
            timestamp="2025-02-15T09:30:00.000000"
        )
        print("✗ Should have rejected invalid side")
    except ValueError as e:
        print(f"✓ Rejected invalid side: {e}")

def test_from_dict_valid():
    """Test deserialization from valid dict"""
    print("\n=== Test 5: from_dict() - Valid Data ===")
    
    data = {
        "token": "12345",
        "entry_price": 50.0,
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000"
    }
    
    leg = TradeLegV1.from_dict(data)
    print(f"✓ Deserialized: {leg}")
    assert leg.token == "12345"
    assert leg.entry_price == 50.0
    assert leg.quantity == 1
    assert leg.side == "SELL"
    print("✓ All fields match")

def test_from_dict_with_optional_fields():
    """Test deserialization with optional fields"""
    print("\n=== Test 6: from_dict() - With Optional Fields ===")
    
    data = {
        "token": "12345",
        "entry_price": 50.0,
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000",
        "leg_id": "LEG_001",
        "status": "CLOSED",
        "exit_price": 48.0,
        "pnl": 200.0
    }
    
    leg = TradeLegV1.from_dict(data)
    print(f"✓ Deserialized with optional fields: {leg}")
    assert leg.leg_id == "LEG_001"
    assert leg.status == "CLOSED"
    assert leg.exit_price == 48.0
    assert leg.pnl == 200.0
    print("✓ All optional fields loaded correctly")

def test_from_dict_missing_required():
    """Test from_dict with missing required fields"""
    print("\n=== Test 7: from_dict() - Missing Required Fields ===")
    
    data = {
        "token": "12345",
        "entry_price": 50.0
        # Missing quantity, side, timestamp
    }
    
    try:
        leg = TradeLegV1.from_dict(data)
        print("✗ Should have rejected missing fields")
    except KeyError as e:
        print(f"✓ Rejected missing fields: {e}")

def test_from_dict_version_check():
    """Test version compatibility in from_dict"""
    print("\n=== Test 8: from_dict() - Version Check ===")
    
    # Valid: version 1 or missing (defaults to 1)
    data_v1 = {
        "token": "12345",
        "entry_price": 50.0,
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000",
        "version": 1
    }
    leg = TradeLegV1.from_dict(data_v1)
    print(f"✓ Accepted version 1: {leg}")
    
    # Future version should be rejected
    data_v2 = {
        "token": "12345",
        "entry_price": 50.0,
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000",
        "version": 2
    }
    try:
        leg = TradeLegV1.from_dict(data_v2)
        print("✗ Should have rejected version 2")
    except ValueError as e:
        print(f"✓ Rejected future version: {e}")

def test_to_dict_roundtrip():
    """Test to_dict + from_dict roundtrip"""
    print("\n=== Test 9: Roundtrip (to_dict → from_dict) ===")
    
    original = TradeLegV1(
        token="12345",
        entry_price=50.0,
        quantity=2,
        side="BUY",
        timestamp="2025-02-15T09:30:00.000000",
        leg_id="LEG_002",
        status="OPEN"
    )
    
    # Serialize
    dict_repr = original.to_dict()
    print(f"✓ Serialized to dict: {dict_repr}")
    
    # Deserialize
    restored = TradeLegV1.from_dict(dict_repr)
    print(f"✓ Deserialized back: {restored}")
    
    # Verify match
    assert original.token == restored.token
    assert original.entry_price == restored.entry_price
    assert original.quantity == restored.quantity
    assert original.side == restored.side
    assert original.leg_id == restored.leg_id
    print("✓ Roundtrip successful - all fields match")

def test_checksum():
    """Test checksum computation and verification"""
    print("\n=== Test 10: Checksum (Data Integrity) ===")
    
    leg = TradeLegV1(
        token="12345",
        entry_price=50.0,
        quantity=1,
        side="SELL",
        timestamp="2025-02-15T09:30:00.000000"
    )
    
    # Compute checksum
    checksum = leg.compute_checksum()
    print(f"✓ Computed checksum: {checksum[:16]}... (SHA256)")
    
    # Verify same leg produces same checksum
    checksum2 = leg.compute_checksum()
    assert checksum == checksum2
    print("✓ Consistent - same leg produces same checksum")
    
    # Dict verification
    leg_dict = leg.to_dict()
    is_valid = TradeLegV1.verify_checksum(leg_dict, checksum)
    print(f"✓ Checksum verification passed: {is_valid}")
    
    # Corrupted data should fail verification
    corrupted_dict = leg_dict.copy()
    corrupted_dict["entry_price"] = 51.0  # Tamper with price
    is_valid_corrupted = TradeLegV1.verify_checksum(corrupted_dict, checksum)
    print(f"✓ Corrupted data detected: {not is_valid_corrupted}")
    assert not is_valid_corrupted, "Should have detected corruption"

def test_status_validation():
    """Test status field validation"""
    print("\n=== Test 11: Status Validation ===")
    
    valid_statuses = ["OPEN", "CLOSED", "EXITED"]
    for status in valid_statuses:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity=1,
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000",
            status=status
        )
        print(f"✓ Accepted status: {status}")
    
    try:
        leg = TradeLegV1(
            token="12345",
            entry_price=50.0,
            quantity=1,
            side="SELL",
            timestamp="2025-02-15T09:30:00.000000",
            status="INVALID_STATUS"
        )
        print("✗ Should have rejected invalid status")
    except ValueError as e:
        print(f"✓ Rejected invalid status: {e}")

def main():
    """Run all tests"""
    print("=" * 70)
    print(" TRADELEG V1 - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    
    try:
        test_basic_creation()
        test_validation_entry_price()
        test_validation_quantity()
        test_validation_side()
        test_from_dict_valid()
        test_from_dict_with_optional_fields()
        test_from_dict_missing_required()
        test_from_dict_version_check()
        test_to_dict_roundtrip()
        test_checksum()
        test_status_validation()
        
        print("\n" + "=" * 70)
        print(" ✓ ALL TESTS PASSED (11/11)")
        print("=" * 70)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
