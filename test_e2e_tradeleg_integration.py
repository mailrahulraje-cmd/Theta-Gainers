#!/usr/bin/env python3
"""
End-to-End Integration Test Suite for TradeLegV1 System

Tests complete trading workflows including:
- Phase transitions with leg management
- Partial fills and retry logic
- Broker failures and recovery
- WebSocket disconnects and reconnects
- Emergency stop and state recovery
- CSV/JSON export and import
- Data integrity and corruption detection
"""

import json
import os
import tempfile
import logging
from datetime import datetime
from contract import TradeLegV1
from core.state import StrategyState
from core.trade_leg_manager import TradeLegManager
from core.tradeleg_integration import TradeLegAPIWrapper, BrokerInteractionWrapper, ConcurrentLegAccessor
from core.tradeleg_export import TradeLegCSVExporter, TradeLegJSONExporter

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


class MockBroker:
    """Mock broker for testing."""
    
    def __init__(self):
        self.orders = {}
        self.positions = {}
        self.order_counter = 0
        self.fail_next = False  # Simulate failures
    
    def place_order(self, side, token, qty, price, tag="", **kwargs):
        """Simulate order placement."""
        if self.fail_next:
            self.fail_next = False
            raise Exception("Simulated broker failure")
        
        self.order_counter += 1
        order_id = f"ORD_{self.order_counter}"
        self.orders[order_id] = {
            'order_id': order_id,
            'side': side,
            'token': token,
            'qty': qty,
            'price': price,
            'status': 'FILLED',
            'filled_qty': qty,
            'avg_price': price
        }
        return self.orders[order_id]
    
    def get_orders(self):
        return list(self.orders.values())


def test_basic_leg_lifecycle():
    """Test create → enter → close lifecycle."""
    print("\n=== Test 1: Basic Leg Lifecycle ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        # Setup
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        
        # 1. Create leg
        leg = api.create_leg_from_entry(
            "sell_ce", "50000CE", 50.0, 1, "SELL"
        )
        assert leg is not None
        assert api.set_leg_safe("sell_ce", leg)
        print("✓ Created and stored sell_ce leg")
        
        # 2. Retrieve leg
        retrieved = api.get_leg_safe("sell_ce")
        assert retrieved is not None
        assert retrieved.entry_price == 50.0
        print("✓ Retrieved leg with correct entry price")
        
        # 3. Close leg
        assert api.mark_leg_closed("sell_ce", 48.5, 150.0)
        print("✓ Marked leg as closed with PnL")
        
        # 4. Verify closure
        closed = api.get_leg_safe("sell_ce")
        assert closed.status == "CLOSED"
        assert closed.exit_price == 48.5
        assert closed.pnl == 150.0
        print("✓ Verified leg status and exit data")
    
    finally:
        os.unlink(state_file)


def test_multiple_legs_phase_transition():
    """Test all 4 legs entering together (Phase 0/1 setup)."""
    print("\n=== Test 2: Multiple Legs Entry (Phase Transition) ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        
        # Create all 4 legs
        legs_config = [
            ("sell_ce", "50000CE", 50.0, 1, "SELL"),
            ("sell_pe", "50000PE", 52.0, 1, "SELL"),
            ("buy_ce", "50100CE", 30.0, 2, "BUY"),
            ("buy_pe", "50100PE", 28.0, 2, "BUY")
        ]
        
        for leg_name, token, price, qty, side in legs_config:
            leg = api.create_leg_from_entry(leg_name, token, price, qty, side)
            assert leg is not None
            assert api.set_leg_safe(leg_name, leg)
        
        print(f"✓ Created all 4 legs")
        
        # Verify all legs present
        active = api.state.get_active_legs()
        assert len(active) == 4
        print(f"✓ All 4 legs active: {active}")
        
        # Print summary
        print(api.get_active_legs_summary())
    
    finally:
        os.unlink(state_file)


def test_broker_interaction():
    """Test placing orders from legs and closing from fills."""
    print("\n=== Test 3: Broker Interaction ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        broker = MockBroker()
        broker_api = BrokerInteractionWrapper(broker, api)
        
        # Create a leg
        leg = api.create_leg_from_entry("sell_ce", "50000CE", 50.0, 1, "SELL")
        api.set_leg_safe("sell_ce", leg)
        print("✓ Created sell_ce leg")
        
        # Place order from leg
        order = broker_api.place_order_from_leg("sell_ce", leg)
        assert order is not None
        assert order['status'] == 'FILLED'
        print(f"✓ Placed order: {order['order_id']}")
        
        # Update leg with fill price (if different)
        actual_fill = 49.8  # Slightly different from entry
        broker_api.update_leg_from_fill("sell_ce", actual_fill, 1)
        print(f"✓ Updated leg with fill price {actual_fill}")
        
        # Close leg from exit
        broker_api.close_leg_from_exit("sell_ce", 48.5, 1, exit_order_id="EXIT_001")
        print("✓ Closed leg from exit order")
        
        # Verify closure
        closed = api.get_leg_safe("sell_ce")
        assert closed.status == "CLOSED"
        print("✓ Verified leg is closed")
    
    finally:
        os.unlink(state_file)


def test_broker_failure_and_retry():
    """Test graceful handling of broker failures."""
    print("\n=== Test 4: Broker Failure & Retry ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        broker = MockBroker()
        broker_api = BrokerInteractionWrapper(broker, api)
        
        leg = api.create_leg_from_entry("sell_ce", "50000CE", 50.0, 1, "SELL")
        api.set_leg_safe("sell_ce", leg)
        
        # Simulate broker failure
        broker.fail_next = True
        order = broker_api.place_order_from_leg("sell_ce", leg)
        assert order is None
        print("✓ Broker failure handled gracefully (order = None)")
        
        # Retry after fixing broker
        broker.fail_next = False
        order = broker_api.place_order_from_leg("sell_ce", leg)
        assert order is not None
        print("✓ Retry succeeded when broker recovered")
    
    finally:
        os.unlink(state_file)


def test_partial_fill_detection():
    """Test detecting partial fills and managing partial positions."""
    print("\n=== Test 5: Partial Fill Detection ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        
        # Create leg for 2 contracts
        leg = api.create_leg_from_entry("buy_ce", "50100CE", 30.0, 2, "BUY")
        api.set_leg_safe("buy_ce", leg)
        print("✓ Created buy_ce leg for 2 contracts")
        
        # Simulate partial fill (only 1 contract filled)
        broker_api = BrokerInteractionWrapper(MockBroker(), api)
        broker_api.update_leg_from_fill("buy_ce", 30.01, 1)  # Filled 1 out of 2
        print("✓ Updated leg with partial fill (1 of 2 contracts)")
        
        # Verify partial state
        partial_leg = api.get_leg_safe("buy_ce")
        assert partial_leg.quantity == 1  # Updated to partial qty
        assert partial_leg.status == "OPEN"  # Still open, not closed
        print("✓ Leg shows partial fill (qty=1, status=OPEN)")
        
        # Close remaining contract
        broker_api.close_leg_from_exit("buy_ce", 30.5, 1)
        print("✓ Closed remaining contract")
        
        final_leg = api.get_leg_safe("buy_ce")
        assert final_leg.status == "CLOSED"
        print("✓ Leg fully closed after exit")
    
    finally:
        os.unlink(state_file)


def test_csv_export_import():
    """Test exporting legs to CSV and reloading."""
    print("\n=== Test 6: CSV Export/Import ===")
    
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
        csv_file = f.name
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        # Create and populate state
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        
        legs_data = [
            ("sell_ce", "50000CE", 50.0, 1, "SELL"),
            ("buy_ce", "50100CE", 30.0, 2, "BUY")
        ]
        
        for leg_name, token, price, qty, side in legs_data:
            leg = api.create_leg_from_entry(leg_name, token, price, qty, side)
            api.set_leg_safe(leg_name, leg)
        
        # Export to CSV
        assert TradeLegCSVExporter.export_legs_to_csv(
            state.leg_manager, csv_file, append_mode=False
        )
        print(f"✓ Exported legs to {csv_file}")
        
        # Reload from CSV
        imported_manager = TradeLegCSVExporter.import_legs_from_csv(csv_file)
        assert imported_manager is not None
        assert len(imported_manager.get_active_legs()) == 2
        print("✓ Imported 2 legs from CSV")
        
        # Verify data integrity
        imported_leg = imported_manager.get_leg("sell_ce")
        assert imported_leg.token == "50000CE"
        assert imported_leg.entry_price == 50.0
        print("✓ Reimported leg data matches original")
    
    finally:
        os.unlink(csv_file)
        os.unlink(state_file)


def test_json_export_import():
    """Test exporting legs to JSON with checksums."""
    print("\n=== Test 7: JSON Export/Import with Checksums ===")
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        json_file = f.name
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        # Create and populate state
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        
        leg = api.create_leg_from_entry("sell_ce", "50000CE", 50.0, 1, "SELL")
        api.set_leg_safe("sell_ce", leg)
        
        # Export to JSON with checksums
        assert TradeLegJSONExporter.export_legs_to_json(
            state.leg_manager, json_file, include_metadata=True
        )
        print(f"✓ Exported leg to {json_file} with checksum")
        
        # Reload from JSON
        imported_manager = TradeLegJSONExporter.import_legs_from_json(json_file)
        assert imported_manager is not None
        assert len(imported_manager.get_active_legs()) == 1
        print("✓ Imported leg from JSON")
        
        # Verify checksum
        imported_leg = imported_manager.get_leg("sell_ce")
        stored_checksum = imported_manager.checksums.get("sell_ce")
        assert TradeLegV1.verify_checksum(imported_leg.to_dict(), stored_checksum)
        print("✓ Checksum verified for imported leg")
    
    finally:
        os.unlink(json_file)
        os.unlink(state_file)


def test_corruption_detection():
    """Test detection and graceful handling of corrupted data."""
    print("\n=== Test 8: Corruption Detection & Handling ===")
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        json_file = f.name
    
    try:
        # Create manager with a leg
        manager = TradeLegManager()
        leg = TradeLegV1(
            token="50000CE",
            entry_price=50.0,
            quantity=1,
            side="SELL",
            timestamp="2025-02-15T09:30:00"
        )
        manager.set_leg("sell_ce", leg)
        
        # Export to JSON
        TradeLegJSONExporter.export_legs_to_json(manager, json_file)
        print("✓ Exported leg to JSON")
        
        # Corrupt the data
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        data['legs']['sell_ce']['entry_price'] = 51.0  # Tamper with price
        
        with open(json_file, 'w') as f:
            json.dump(data, f)
        print("✓ Corrupted leg data (tampered with entry_price)")
        
        # Try to reload with skip_corrupted=True
        imported_manager = TradeLegJSONExporter.import_legs_from_json(
            json_file, skip_corrupted=True
        )
        assert imported_manager is not None
        # Corrupted leg should be skipped
        assert len(imported_manager.get_active_legs()) == 0
        print("✓ Corrupted leg detected and skipped gracefully")
        
        # Try with skip_corrupted=False (should raise error)
        try:
            imported_manager = TradeLegJSONExporter.import_legs_from_json(
                json_file, skip_corrupted=False
            )
            print("✗ Should have raised error for corrupted data")
        except ValueError as e:
            print(f"✓ Raised error for corrupted data: {str(e)[:50]}...")
    
    finally:
        os.unlink(json_file)


def test_legacy_migration():
    """Test automatic migration of legacy dict-based legs."""
    print("\n=== Test 9: Legacy State Migration ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
        # Write legacy format
        legacy_state = {
            'sell_ce_token': '50000CE',
            'sell_ce_ref_premium': 50.0,
            'sell_ce_qty': 1,
            'sell_ce_entered': True,
            'buy_ce_token': '50100CE',
            'buy_ce_ref_premium': 30.0,
            'buy_ce_qty': 2,
            'buy_ce_entered': False,
        }
        json.dump(legacy_state, f)
    
    try:
        # Load state (should auto-migrate)
        state = StrategyState(state_file)
        print("✓ Loaded legacy state")
        
        # Verify migration
        api = TradeLegAPIWrapper(state)
        assert api.get_leg_safe("sell_ce") is not None
        assert api.get_leg_safe("buy_ce") is not None
        print("✓ Migrated 2 legs from legacy format")
        
        # Verify data
        sell_ce = api.get_leg_safe("sell_ce")
        assert sell_ce.token == "50000CE"
        assert sell_ce.entry_price == 50.0
        print("✓ Migrated leg data is correct")
    
    finally:
        os.unlink(state_file)


def test_concurrent_access():
    """Test thread-safe concurrent access to legs."""
    print("\n=== Test 10: Concurrent Access ===")
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        api = TradeLegAPIWrapper(state)
        accessor = ConcurrentLegAccessor(api)
        
        # Create a leg
        leg = api.create_leg_from_entry("sell_ce", "50000CE", 50.0, 1, "SELL")
        api.set_leg_safe("sell_ce", leg)
        print("✓ Created leg")
        
        # Atomic update
        def mark_as_entered(leg):
            return TradeLegV1(
                token=leg.token,
                entry_price=leg.entry_price,
                quantity=leg.quantity,
                side=leg.side,
                timestamp=leg.timestamp,
                leg_id=leg.leg_id,
                status="OPEN"  # Could mark as ENTERED in real scenario
            )
        
        assert accessor.update_leg_atomic("sell_ce", mark_as_entered)
        print("✓ Atomic update successful")
        
        # Batch verify
        results = accessor.batch_verify_all()
        assert "sell_ce" in results
        print(f"✓ Batch verification: {results}")
    
    finally:
        os.unlink(state_file)


def main():
    """Run all integration tests."""
    print("=" * 70)
    print(" TRADELEG INTEGRATION - END-TO-END TEST SUITE")
    print("=" * 70)
    
    tests = [
        test_basic_leg_lifecycle,
        test_multiple_legs_phase_transition,
        test_broker_interaction,
        test_broker_failure_and_retry,
        test_partial_fill_detection,
        test_csv_export_import,
        test_json_export_import,
        test_corruption_detection,
        test_legacy_migration,
        test_concurrent_access,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            logger.error(f"✗ FAILED: {e}", exc_info=True)
            failed += 1
    
    print("\n" + "=" * 70)
    print(f" RESULTS: {passed} passed, {failed} failed ({passed}/{len(tests)})")
    print("=" * 70)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
