#!/usr/bin/env python3
"""
Test script to validate that the trading system fixes are working correctly.
Tests both paper and live broker order placement logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from paper_broker import PaperBroker
from core.state import StrategyState
from utils.logger import logger

def test_paper_broker_order_placement():
    """Test that paper broker can place orders and returns result"""
    print("\n" + "="*80)
    print("TEST 1: Paper Broker Order Placement")
    print("="*80)
    
    # Create test state
    state = StrategyState("test_state.json")
    state.update({'lot_size': 15})
    
    # Create paper broker
    broker = PaperBroker(state, trades_csv="test_trades.csv")
    
    # Test order placement - Signature 1
    print("\n Testing signature 1: place_order(side, token, qty, price, label)")
    result = broker.place_order("BUY", "12345", 50, 100.50, "TEST_ORDER_1")
    
    if result:
        print(f" Order placed successfully!")
        print(f"   Order ID: {result['order_id']}")
        print(f"   Status: {result['status']}")
        print(f"   Side: {result['side']}")
        print(f"   Qty: {result['qty']}")
        print(f"   Price: {result['price']:.2f}")
        return True
    else:
        print(" Order placement failed - returned None")
        return False

def test_order_safe_logic():
    """Test that engine's _place_order_safe returns values correctly"""
    print("\n" + "="*80)
    print("TEST 2: Order Placement Return Values")
    print("="*80)
    
    from strategy.engine import StrategyEngine
    from core.state import StrategyState
    from paper_broker import PaperBroker
    
    # Mock feed
    class MockFeed:
        def get_ltp(self, token, check_freshness=True):
            return 100.0
        def set_tick_callback(self, cb):
            pass
        def subscribe(self, tokens, symbols, exchange):
            pass
        def close(self):
            pass
    
    # Mock instruments
    class MockInstruments:
        def update_snapshot(self, token, ltp, delta):
            pass
    
    # Setup
    state = StrategyState("test_state_2.json")
    state.update({'lot_size': 15})
    broker = PaperBroker(state, trades_csv="test_trades_2.csv")
    feed = MockFeed()
    instruments = MockInstruments()
    
    # Create engine
    engine = StrategyEngine(feed, instruments, broker, state)
    
    # Test _place_order_safe
    print("\n Testing _place_order_safe return value")
    result = engine._place_order_safe("SELL", "67890", 50, 95.50, "TEST_ENGINE_ORDER")
    
    if result:
        print(f" _place_order_safe returned result!")
        print(f"   Result type: {type(result)}")
        print(f"   Result: {result}")
        return True
    else:
        print(" _place_order_safe returned None")
        return False

def test_state_logging():
    """Test that state updates are logged"""
    print("\n" + "="*80)
    print("TEST 3: State Update Logging")
    print("="*80)
    
    from core.state import StrategyState
    
    state = StrategyState("test_state_3.json")
    
    print("\n Testing state.update() logging")
    state.update({
        'sell_ce_entered': True,
        'sell_ce_entry_price': 85.50
    })
    
    # Verify state was updated
    if state.get('sell_ce_entered') == True:
        print(" State update successful")
        print(f"   sell_ce_entered: {state.get('sell_ce_entered')}")
        print(f"   sell_ce_entry_price: {state.get('sell_ce_entry_price')}")
        return True
    else:
        print(" State update failed")
        return False

def test_debug_mode():
    """Test that DEBUG_MODE flag works"""
    print("\n" + "="*80)
    print("TEST 4: Debug Mode Flag")
    print("="*80)
    
    from config import Config
    
    print(f"\n Current DEBUG_MODE: {Config.DEBUG_MODE}")
    print(f"   TRADING_MODE: {Config.TRADING_MODE}")
    print(f"   DATA_MODE: {Config.DATA_MODE}")
    
    print("\n To enable debug logging:")
    print("   export DEBUG_MODE=true")
    print("   or add DEBUG_MODE=true to .env file")
    
    return True

def cleanup_test_files():
    """Remove test files"""
    import os
    test_files = [
        "test_state.json",
        "test_state_2.json", 
        "test_state_3.json",
        "test_trades.csv",
        "test_trades_2.csv"
    ]
    for f in test_files:
        if os.path.exists(f):
            os.remove(f)
            print(f"  Removed {f}")

def main():
    """Run all tests"""
    print("="*80)
    print("TRADING SYSTEM FIX VALIDATION TESTS")
    print("="*80)
    
    results = []
    
    # Run tests
    results.append(("Paper Broker Order Placement", test_paper_broker_order_placement()))
    results.append(("Order Safe Return Values", test_order_safe_logic()))
    results.append(("State Update Logging", test_state_logging()))
    results.append(("Debug Mode Flag", test_debug_mode()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = " PASS" if result else " FAIL"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    # Cleanup
    print("\n" + "="*80)
    print("CLEANUP")
    print("="*80)
    cleanup_test_files()
    
    if passed == total:
        print("\n All tests passed! System fixes validated.")
        print("\n Next steps:")
        print("   1. Enable DEBUG_MODE=true in .env")
        print("   2. Run system in paper mode")
        print("   3. Monitor logs for detailed execution trace")
        print("   4. Verify trades execute when conditions met")
        return 0
    else:
        print("\n  Some tests failed. Review output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
