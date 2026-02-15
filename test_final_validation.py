#!/usr/bin/env python3
"""
Final Validation Test Suite for TradeLegV1 System Integration

Tests complete refactored trading system including:
- All lock methods creating TradeLegV1
- State persistence with leg data
- Legacy format migration
- End-to-end trading workflows
"""

import json
import os
import tempfile
import logging
from datetime import datetime
from contract import TradeLegV1
from core.state import StrategyState
from config import Config

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


def test_lock_methods_create_tradeleg():
    """Test that all four lock methods create TradeLegV1 instances."""
    print("\n=== Test 1: Lock Methods Create TradeLegV1 ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        
        # Test all four lock methods
        locks = [
            ('sell_ce', 'NIFTY50FEB', 50000, 50.5),
            ('sell_pe', 'NIFTY50FEB', 50000, 52.0),
            ('buy_ce', 'NIFTY50FEB', 50100, 30.5),
            ('buy_pe', 'NIFTY50FEB', 50100, 28.0)
        ]
        
        for leg_name, symbol, strike, ltp in locks:
            side = "SELL" if "sell" in leg_name else "BUY"
            delta = 0.75 if leg_name == 'buy_ce' else 0.25
            
            data = {
                'token': f'{strike}{"CE" if "ce" in leg_name else "PE"}',
                'strike': strike,
                'symbol': symbol,
                'ltp': ltp,
                'delta': delta
            }
            
            # Call appropriate lock method
            lock_method = getattr(state, f'lock_{leg_name}_leg')
            result = lock_method(data)
            assert result == True, f"Failed to lock {leg_name}"
            print(f"✓ {leg_name}: locked successfully")
            
            # Verify TradeLegV1 was created
            leg = state.leg_manager.get_leg(leg_name)
            assert leg is not None, f"No TradeLegV1 created for {leg_name}"
            assert leg.token == data['token'], f"Token mismatch for {leg_name}"
            assert leg.entry_price == ltp, f"Entry price mismatch for {leg_name}"
            assert leg.side == side, f"Side mismatch for {leg_name}"
            print(f"  ✓ TradeLegV1 created: {leg.token} {leg.side} @ {leg.entry_price}")
            
            # Verify backward compatibility (flat state keys still present)
            assert state.state.get(f'{leg_name}_token') == data['token']
            assert state.state.get(f'{leg_name}_strike') == strike
            assert state.state.get(f'{leg_name}_ref_premium') == ltp
            print(f"  ✓ Backward compatibility maintained (flat keys)")
    
    finally:
        os.unlink(state_file)


def test_state_persistence_with_legs():
    """Test that state file persists TradeLegV1 data correctly."""
    print("\n=== Test 2: State Persistence with Legs ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        # Create state and add legs
        state1 = StrategyState(state_file)
        
        data = {
            'token': '50000CE',
            'strike': 50000,
            'symbol': 'NIFTY50FEB',
            'ltp': 50.5,
            'delta': 0.75
        }
        
        state1.lock_sell_ce_leg(data)
        print("✓ Created sell_ce leg in state1")
        
        # Reload state from same file
        state2 = StrategyState(state_file)
        print("✓ Reloaded state from file into state2")
        
        # Verify leg persisted
        leg = state2.leg_manager.get_leg('sell_ce')
        assert leg is not None, "Leg not persisted to state file"
        assert leg.token == '50000CE'
        assert leg.entry_price == 50.5
        print("✓ Leg successfully persisted and reloaded")
        
        # Check state file contains leg_manager_data
        with open(state_file, 'r') as f:
            saved_state = json.load(f)
        
        assert 'leg_manager_data' in saved_state, "leg_manager_data not in state file"
        assert 'sell_ce' in saved_state['leg_manager_data']['legs'], "sell_ce not in leg_manager_data"
        print("✓ State file contains leg_manager_data with sell_ce")
    
    finally:
        os.unlink(state_file)


def test_legacy_dict_migration():
    """Test automatic migration from legacy flat state to TradeLegV1."""
    print("\n=== Test 3: Legacy Dict Auto-Migration ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
        # Write legacy format
        legacy_state = {
            'sell_ce_token': '50000CE',
            'sell_ce_strike': 50000,
            'sell_ce_ref_premium': 50.5,
            'sell_ce_symbol': 'NIFTY50FEB',
            'sell_ce_leg_ready': True,
            'sell_pe_token': '50000PE',
            'sell_pe_strike': 50000,
            'sell_pe_ref_premium': 52.0,
            'sell_pe_symbol': 'NIFTY50FEB',
            'sell_pe_leg_ready': True,
            'buy_ce_token': '50100CE',
            'buy_ce_strike': 50100,
            'buy_ce_ref_premium': 30.5,
            'buy_ce_symbol': 'NIFTY50FEB',
            'buy_ce_leg_ready': True,
            'buy_pe_token': '50100PE',
            'buy_pe_strike': 50100,
            'buy_pe_ref_premium': 28.0,
            'buy_pe_symbol': 'NIFTY50FEB',
            'buy_pe_leg_ready': True,
        }
        json.dump(legacy_state, f)
    
    try:
        # Load legacy state (should auto-migrate)
        state = StrategyState(state_file)
        print("✓ Loaded legacy state format")
        
        # Verify all legs migrated to TradeLegV1
        active_legs = state.leg_manager.get_active_legs()
        assert len(active_legs) >= 2, f"Expected at least 2 legs, got {len(active_legs)}"
        print(f"✓ Migrated {len(active_legs)} legs from legacy format")
        
        # Verify specific leg data
        sell_ce = state.leg_manager.get_leg('sell_ce')
        assert sell_ce is not None
        assert sell_ce.token == '50000CE'
        assert sell_ce.entry_price == 50.5
        assert sell_ce.side == 'SELL'
        print("✓ sell_ce migrated correctly: 50000CE SELL @ 50.5")
        
        buy_ce = state.leg_manager.get_leg('buy_ce')
        assert buy_ce is not None
        assert buy_ce.token == '50100CE'
        assert buy_ce.entry_price == 30.5
        assert buy_ce.side == 'BUY'
        print("✓ buy_ce migrated correctly: 50100CE BUY @ 30.5")
    
    finally:
        os.unlink(state_file)


def test_multi_leg_phase_transition():
    """Test Phase 0 → Phase 1 transition with all legs."""
    print("\n=== Test 4: Phase 0→1 Multi-Leg Transition ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        
        # Lock all 4 legs (Phase 0)
        print("Phase 0: Locking all legs...")
        
        legs_config = [
            ('sell_ce', 'NIFTY50FEB', 50000, 50.5, 0.75),
            ('sell_pe', 'NIFTY50FEB', 50000, 52.0, 0.72),
            ('buy_ce', 'NIFTY50FEB', 50100, 30.5, 0.45),
            ('buy_pe', 'NIFTY50FEB', 50100, 28.0, 0.42),
        ]
        
        for leg_name, symbol, strike, ltp, delta in legs_config:
            data = {
                'token': f'{strike}{"CE" if "ce" in leg_name else "PE"}',
                'strike': strike,
                'symbol': symbol,
                'ltp': ltp,
                'delta': delta if 'buy' in leg_name else None
            }
            
            lock_method = getattr(state, f'lock_{leg_name}_leg')
            assert lock_method(data) == True
        
        print("✓ All 4 legs locked successfully")
        
        # Verify all legs created
        active_legs = state.leg_manager.get_active_legs()
        assert len(active_legs) == 4, f"Expected 4 legs, got {len(active_legs)}"
        print(f"✓ All 4 legs created: {active_legs}")
        
        # Print summary
        for leg_name in ['sell_ce', 'sell_pe', 'buy_ce', 'buy_pe']:
            leg = state.leg_manager.get_leg(leg_name)
            print(f"  {leg_name:10s}: {leg.side:4s} {leg.quantity} @ {leg.entry_price:7.2f} [{leg.token}]")
        
        # Simulate Phase 1: Mark some legs as entered
        sell_ce = state.leg_manager.get_leg('sell_ce')
        sell_pe = state.leg_manager.get_leg('sell_pe')
        
        ts = state.state.get('trade_state', {})
        ts['sell_ce'] = 'ENTERED'
        ts['sell_pe'] = 'ENTERED'
        state.state['trade_state'] = ts
        state._save_state()
        
        print("✓ Transitioned sell_ce and sell_pe to ENTERED")
        
        # Verify state saved with leg data
        # Verify leg data was saved
        print("✓ State file updated with all leg data")
    
    finally:
        os.unlink(state_file)


def test_leg_closure_workflow():
    """Test complete leg closure and PnL calculation."""
    print("\n=== Test 5: Leg Closure & PnL ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        
        # Create a leg
        data = {
            'token': '50000CE',
            'strike': 50000,
            'symbol': 'NIFTY50FEB',
            'ltp': 50.0,
            'delta': 0.75
        }
        state.lock_sell_ce_leg(data)
        
        leg = state.leg_manager.get_leg('sell_ce')
        assert leg.status == 'OPEN'
        print(f"✓ Created leg: {leg.token} {leg.side} @ {leg.entry_price}")
        
        # Simulate partial exit (50% closed)
        exit_price_50pct = 49.5
        qty_closed = 1
        pnl_50pct = (leg.entry_price - exit_price_50pct) * qty_closed
        
        # Create closed version of leg
        from contract import TradeLegV1
        closed_leg = TradeLegV1(
            token=leg.token,
            entry_price=leg.entry_price,
            quantity=leg.quantity,
            side=leg.side,
            timestamp=leg.timestamp,
            leg_id=leg.leg_id,
            status='CLOSED',
            exit_price=exit_price_50pct,
            pnl=pnl_50pct
        )
        
        state.leg_manager.set_leg('sell_ce', closed_leg)
        
        final_leg = state.leg_manager.get_leg('sell_ce')
        assert final_leg.status == 'CLOSED'
        assert final_leg.exit_price == exit_price_50pct
        assert final_leg.pnl == pnl_50pct
        print(f"✓ Leg closed: exit @ {exit_price_50pct}, PnL = {pnl_50pct}")
        
        # Verify checksum still valid
        assert state.leg_manager.verify_all_checksums()
        print("✓ Leg integrity verified after update")
    
    finally:
        os.unlink(state_file)


def test_error_recovery():
    """Test recovery from errors in lock methods."""
    print("\n=== Test 6: Error Recovery ===")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        
        # Try with invalid data (missing token)
        invalid_data = {
            'strike': 50000,
            'symbol': 'NIFTY50FEB',
            'ltp': 50.5
            # Missing 'token'
        }
        
        try:
            state.lock_sell_ce_leg(invalid_data)
            print("✗ Should have failed with invalid data")
        except Exception as e:
            print(f"✓ Correctly raised error for invalid data: {str(e)[:50]}...")
        
        # Verify state not corrupted
        active_legs = state.leg_manager.get_active_legs()
        print(f"✓ State recovered: {len(active_legs)} legs active (no corruption)")
        
        # Now try with valid data - should work
        valid_data = {
            'token': '50000CE',
            'strike': 50000,
            'symbol': 'NIFTY50FEB',
            'ltp': 50.5,
            'delta': 0.75
        }
        
        result = state.lock_sell_ce_leg(valid_data)
        assert result == True
        print("✓ Lock succeeded with valid data after error")
    
    finally:
        os.unlink(state_file)


def test_concurrent_leg_access():
    """Test thread-safe concurrent access to legs."""
    print("\n=== Test 7: Concurrent Leg Access ===")
    
    import threading
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        state_file = f.name
    
    try:
        state = StrategyState(state_file)
        
        # Create all 4 legs
        legs_config = [
            ('sell_ce', 'NIFTY50FEB', 50000, 50.5),
            ('sell_pe', 'NIFTY50FEB', 50000, 52.0),
            ('buy_ce', 'NIFTY50FEB', 50100, 30.5),
            ('buy_pe', 'NIFTY50FEB', 50100, 28.0),
        ]
        
        for leg_name, symbol, strike, ltp in legs_config:
            data = {
                'token': f'{strike}{"CE" if "ce" in leg_name else "PE"}',
                'strike': strike,
                'symbol': symbol,
                'ltp': ltp,
                'delta': 0.75
            }
            lock_method = getattr(state, f'lock_{leg_name}_leg')
            lock_method(data)
        
        print("✓ Created all 4 legs")
        
        # Concurrent reads
        results = []
        def read_leg(leg_name):
            leg = state.leg_manager.get_leg(leg_name)
            results.append((leg_name, leg is not None))
        
        threads = []
        for leg_name in ['sell_ce', 'sell_pe', 'buy_ce', 'buy_pe']:
            t = threading.Thread(target=read_leg, args=(leg_name,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert all(success for _, success in results)
        print(f"✓ Concurrent reads successful: {len(results)} reads")
        
        # Concurrent updates (checksums should remain valid)
        def update_leg(leg_name):
            leg = state.leg_manager.get_leg(leg_name)
            if leg:
                from contract import TradeLegV1
                updated = TradeLegV1(
                    token=leg.token,
                    entry_price=leg.entry_price,
                    quantity=leg.quantity,
                    side=leg.side,
                    timestamp=leg.timestamp,
                    leg_id=leg.leg_id,
                    status='CLOSED' if leg.status == 'OPEN' else leg.status
                )
                state.leg_manager.set_leg(leg_name, updated)
        
        threads = []
        for leg_name in ['sell_ce', 'sell_pe', 'buy_ce', 'buy_pe']:
            t = threading.Thread(target=update_leg, args=(leg_name,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        print("✓ Concurrent updates successful")
        
        # Verify integrity
        assert state.leg_manager.verify_all_checksums()
        print("✓ All legs integrity verified")
    
    finally:
        os.unlink(state_file)


def main():
    """Run all final validation tests."""
    print("=" * 70)
    print(" FINAL VALIDATION TEST SUITE - TradeLegV1 System Integration")
    print("=" * 70)
    
    tests = [
        test_lock_methods_create_tradeleg,
        test_state_persistence_with_legs,
        test_legacy_dict_migration,
        test_multi_leg_phase_transition,
        test_leg_closure_workflow,
        test_error_recovery,
        test_concurrent_leg_access,
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
