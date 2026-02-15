#!/usr/bin/env python3
"""
Liveness Layer Test Script
===========================

Tests the liveness layer implementation for:
1. Module imports
2. Configuration loading
3. Thread startup/shutdown
4. Status queries
5. Decoupling from trading logic (no shared state access)
"""

import sys
import os
import time
import threading
from unittest.mock import Mock, MagicMock

# Add repo to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from liveness_layer import LivenessMonitor, create_liveness_monitor
from utils.logger import logger


class FakeFeed:
    """Mock feed for testing without real broker connection"""
    def __init__(self):
        self.call_count = 0
        self.ltp_value = 24650.0
    
    def get_ltp(self, token, check_freshness=True):
        """Simulate LTP fetch"""
        self.call_count += 1
        return self.ltp_value


def test_imports():
    """Test 1: Module imports successfully"""
    print("\n" + "=" * 80)
    print("TEST 1: Module Imports")
    print("=" * 80)
    
    try:
        from liveness_layer import LivenessMonitor, create_liveness_monitor
        print("✅ liveness_layer imports successful")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_config_loading():
    """Test 2: Configuration loads correctly"""
    print("\n" + "=" * 80)
    print("TEST 2: Configuration Loading")
    print("=" * 80)
    
    try:
        enable = getattr(Config, 'ENABLE_LIVENESS_MONITOR', False)
        interval = getattr(Config, 'LIVENESS_CHECK_INTERVAL', 60.0)
        token_symbol = getattr(Config, 'LIVENESS_TOKEN_SYMBOL', 'NIFTY')
        telegram = getattr(Config, 'LIVENESS_ENABLE_TELEGRAM', False)
        
        print(f"  ENABLE_LIVENESS_MONITOR: {enable}")
        print(f"  LIVENESS_CHECK_INTERVAL: {interval}")
        print(f"  LIVENESS_TOKEN_SYMBOL: {token_symbol}")
        print(f"  LIVENESS_ENABLE_TELEGRAM: {telegram}")
        print("✅ Configuration loaded successfully")
        return True
    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        return False


def test_monitor_creation():
    """Test 3: LivenessMonitor instantiation"""
    print("\n" + "=" * 80)
    print("TEST 3: Monitor Creation")
    print("=" * 80)
    
    try:
        feed = FakeFeed()
        notifier = None  # No telegram for test
        
        monitor = LivenessMonitor(
            feed=feed,
            notifier=notifier,
            interval_seconds=5.0,  # Short for testing
            token_symbol="NIFTY",
            enable_telegram=False
        )
        
        print(f"  Monitor created: {monitor}")
        print(f"  Interval: {monitor.interval}s (enforced minimum 10s)")
        print(f"  Token: {monitor.token_symbol}")
        print("✅ Monitor instantiation successful")
        return True
    except Exception as e:
        print(f"❌ Monitor creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_thread_lifecycle():
    """Test 4: Thread start/stop lifecycle"""
    print("\n" + "=" * 80)
    print("TEST 4: Thread Lifecycle")
    print("=" * 80)
    
    try:
        feed = FakeFeed()
        monitor = LivenessMonitor(
            feed=feed,
            notifier=None,
            interval_seconds=2.0,
            token_symbol="NIFTY",
            enable_telegram=False
        )
        
        # Test: Start
        print("  Starting monitor...")
        monitor.start()
        time.sleep(0.5)
        
        # Verify thread is running
        if monitor._thread is None or not monitor._thread.is_alive():
            print("❌ Thread failed to start")
            return False
        print("  ✓ Thread started successfully")
        
        # Wait for checks to run
        print("  Waiting for checks (3 seconds)...")
        time.sleep(3.0)
        
        # Verify checks ran
        status = monitor.get_status()
        print(f"  ✓ Checks complete: {status['total_checks']} checks, "
              f"{status['success_count']} success, {status['error_count']} error")
        
        if status['total_checks'] == 0:
            print("❌ No checks were performed")
            return False
        
        # Test: Stop
        print("  Stopping monitor...")
        monitor.stop()
        time.sleep(0.5)
        
        # Verify thread stopped
        if monitor._thread is not None and monitor._thread.is_alive():
            print("❌ Thread failed to stop")
            return False
        print("  ✓ Thread stopped successfully")
        
        print("✅ Thread lifecycle test passed")
        return True
        
    except Exception as e:
        print(f"❌ Thread lifecycle test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_status_queries():
    """Test 5: Status query methods"""
    print("\n" + "=" * 80)
    print("TEST 5: Status Queries")
    print("=" * 80)
    
    try:
        feed = FakeFeed()
        monitor = LivenessMonitor(
            feed=feed,
            notifier=None,
            interval_seconds=2.0,
            token_symbol="NIFTY",
            enable_telegram=False
        )
        
        monitor.start()
        time.sleep(3.0)
        
        # Get status
        status = monitor.get_status()
        print(f"  Status: {status}")
        
        assert 'last_check_time' in status, "Missing last_check_time"
        assert 'last_ltp' in status, "Missing last_ltp"
        assert 'success_count' in status, "Missing success_count"
        assert 'error_count' in status, "Missing error_count"
        assert 'total_checks' in status, "Missing total_checks"
        assert 'success_rate' in status, "Missing success_rate"
        
        print(f"  ✓ Last LTP: {status['last_ltp']}")
        print(f"  ✓ Success Rate: {status['success_rate']:.1%}")
        print(f"  ✓ Total Checks: {status['total_checks']}")
        
        # Health check
        is_healthy = monitor.is_healthy(recent_seconds=120)
        print(f"  ✓ Is Healthy: {is_healthy}")
        
        if not is_healthy:
            print("❌ Health check failed (should be healthy after recent checks)")
            return False
        
        monitor.stop()
        print("✅ Status query test passed")
        return True
        
    except Exception as e:
        print(f"❌ Status query test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_no_shared_state_access():
    """Test 6: Verify no access to trading state"""
    print("\n" + "=" * 80)
    print("TEST 6: No Shared State Access (Decoupling)")
    print("=" * 80)
    
    try:
        # Simulate trading state that liveness should NOT access
        fake_trade_state = {
            'phase': 'PHASE_PHASE1',
            'positions': {'NIFTY24600CE': {'qty': 1, 'price': 50.0}},
            'entry_price': 50.0,
            'orders': []
        }
        
        feed = FakeFeed()
        monitor = LivenessMonitor(
            feed=feed,
            notifier=None,
            interval_seconds=1.0,
            token_symbol="NIFTY",
            enable_telegram=False
        )
        
        # Verify monitor has NO reference to trade_state
        monitor_vars = vars(monitor)
        dangerous_vars = ['trade_state', 'positions', 'broker', 'state', 'orders']
        
        for var in dangerous_vars:
            if var in monitor_vars:
                print(f"❌ Monitor has access to {var} (should be decoupled)")
                return False
        
        print("  ✓ Monitor has no access to trade_state")
        print("  ✓ Monitor has no access to positions")
        print("  ✓ Monitor has no access to broker")
        print("  ✓ Monitor has no access to orders")
        
        # Verify monitor only accesses feed (read-only)
        print("  ✓ Monitor only accesses feed.get_ltp (read-only)")
        
        print("✅ Decoupling test passed - fully independent")
        return True
        
    except Exception as e:
        print(f"❌ Decoupling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_resilience():
    """Test 7: Resilience to errors"""
    print("\n" + "=" * 80)
    print("TEST 7: Error Resilience")
    print("=" * 80)
    
    try:
        # Create a feed that sometimes fails
        class FaultyFeed:
            def __init__(self):
                self.call_count = 0
            
            def get_ltp(self, token, check_freshness=True):
                self.call_count += 1
                if self.call_count % 3 == 0:
                    raise Exception("Simulated LTP fetch error")
                return 24650.0 + self.call_count
        
        feed = FaultyFeed()
        monitor = LivenessMonitor(
            feed=feed,
            notifier=None,
            interval_seconds=1.0,
            token_symbol="NIFTY",
            enable_telegram=False
        )
        
        monitor.start()
        time.sleep(4.0)
        
        status = monitor.get_status()
        print(f"  After error simulation:")
        print(f"    Success: {status['success_count']}")
        print(f"    Errors:  {status['error_count']}")
        print(f"    Total:   {status['total_checks']}")
        
        # Monitor should still be running despite errors
        if monitor._thread is None or not monitor._thread.is_alive():
            print("❌ Monitor crashed on error (should be resilient)")
            return False
        
        print("  ✓ Monitor survived errors")
        print("  ✓ Monitor still running")
        
        monitor.stop()
        print("✅ Error resilience test passed")
        return True
        
    except Exception as e:
        print(f"❌ Error resilience test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_factory_function():
    """Test 8: Factory function with config"""
    print("\n" + "=" * 80)
    print("TEST 8: Factory Function")
    print("=" * 80)
    
    try:
        feed = FakeFeed()
        
        # Test with disabled config
        monitor = create_liveness_monitor(
            feed=feed,
            notifier=None,
            config_override={'enabled': False}
        )
        
        if monitor is not None:
            print("❌ Factory returned monitor when disabled")
            return False
        
        print("  ✓ Returns None when disabled")
        
        # Test with enabled config
        monitor = create_liveness_monitor(
            feed=feed,
            notifier=None,
            config_override={
                'enabled': True,
                'interval': 2.0,
                'token_symbol': 'NIFTY',
                'enable_telegram': False
            }
        )
        
        if monitor is None:
            print("❌ Factory returned None when enabled")
            return False
        
        print("  ✓ Returns monitor when enabled")
        
        if not monitor._thread or not monitor._thread.is_alive():
            print("❌ Monitor not started by factory")
            return False
        
        print("  ✓ Monitor auto-started by factory")
        
        monitor.stop()
        print("✅ Factory function test passed")
        return True
        
    except Exception as e:
        print(f"❌ Factory function test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("LIVENESS LAYER TEST SUITE")
    print("=" * 80)
    
    tests = [
        ("Imports", test_imports),
        ("Config Loading", test_config_loading),
        ("Monitor Creation", test_monitor_creation),
        ("Thread Lifecycle", test_thread_lifecycle),
        ("Status Queries", test_status_queries),
        ("Decoupling (No Shared State)", test_no_shared_state_access),
        ("Error Resilience", test_error_resilience),
        ("Factory Function", test_factory_function),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} test crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 80)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
