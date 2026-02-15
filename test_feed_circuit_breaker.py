"""
Test Feed Circuit Breaker Implementation in ExecutionGateway

Tests:
1. Feed HEALTHY → Entry allowed
2. Feed CRITICAL → Entry blocked, Exit allowed
3. Feed DEAD → Entry blocked, Exit blocked
4. Feed recovers → Orders allowed again
5. Thread safety and concurrent access
6. Notifier integration
"""

import threading
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from core.execution_gateway import ExecutionGateway, get_execution_gateway
from utils.logger import logger


class MockFeed:
    """Mock feed for testing"""
    
    def __init__(self):
        self.status = 'OK'
        self.metadata = 'All tokens receiving ticks'
        self.lock = threading.Lock()
    
    def get_health_status(self):
        """Return current feed status"""
        with self.lock:
            return self.status, self.metadata
    
    def set_status(self, status, metadata):
        """Change feed status for testing"""
        with self.lock:
            self.status = status
            self.metadata = metadata


class MockNotifier:
    """Mock notifier for testing"""
    
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()
    
    def send_trade_log(self, msg):
        """Record sent messages"""
        with self.lock:
            self.messages.append(msg)
            print(f"[NOTIFIER] {msg}")


class TestFeedCircuitBreaker(unittest.TestCase):
    """Test ExecutionGateway feed circuit breaker"""
    
    def setUp(self):
        """Setup fresh gateway for each test"""
        # Create new gateway instance for isolated testing
        self.gateway = ExecutionGateway()
        self.mock_feed = MockFeed()
        self.gateway.set_feed(self.mock_feed)
        
        self.mock_notifier = MockNotifier()
        self.gateway.set_notifier(self.mock_notifier)
    
    def test_01_feed_healthy_entry_allowed(self):
        """Test Case 1: Feed HEALTHY → Entry allowed"""
        print("\n" + "="*70)
        print("TEST 1: Feed HEALTHY → Entry allowed")
        print("="*70)
        
        self.mock_feed.set_status('OK', 'All tokens receiving ticks')
        
        # Entry order should be allowed
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        self.assertTrue(allowed, f"Entry should be allowed: {reason}")
        print("✓ Entry allowed when feed is OK")
    
    def test_02_feed_healthy_exit_allowed(self):
        """Test Case 1b: Feed HEALTHY → Exit allowed"""
        print("\n" + "="*70)
        print("TEST 1b: Feed HEALTHY → Exit allowed")
        print("="*70)
        
        self.mock_feed.set_status('OK', 'All tokens receiving ticks')
        
        # Exit order should be allowed
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='SELL',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=False
        )
        
        self.assertTrue(allowed, f"Exit should be allowed: {reason}")
        print("✓ Exit allowed when feed is OK")
    
    def test_03_feed_critical_entry_blocked(self):
        """Test Case 2: Feed CRITICAL → Entry blocked"""
        print("\n" + "="*70)
        print("TEST 2: Feed CRITICAL → Entry blocked")
        print("="*70)
        
        self.mock_feed.set_status('CRITICAL', '3 critical, 2 degraded')
        
        # Entry order should be BLOCKED
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        self.assertFalse(allowed, "Entry should be blocked on CRITICAL feed")
        self.assertIn('CRITICAL', reason)
        print(f"✓ Entry blocked: {reason}")
        print(f"✓ Notification sent: {len(self.mock_notifier.messages) > 0}")
    
    def test_04_feed_critical_exit_allowed(self):
        """Test Case 2b: Feed CRITICAL → Exit allowed"""
        print("\n" + "="*70)
        print("TEST 2b: Feed CRITICAL → Exit allowed")
        print("="*70)
        
        self.mock_feed.set_status('CRITICAL', '3 critical, 2 degraded')
        
        # Exit order should be ALLOWED
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='SELL',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=False
        )
        
        self.assertTrue(allowed, f"Exit should be allowed during CRITICAL: {reason}")
        print("✓ Exit allowed when feed is CRITICAL")
    
    def test_05_feed_dead_entry_blocked(self):
        """Test Case 3: Feed DEAD → Entry blocked"""
        print("\n" + "="*70)
        print("TEST 3: Feed DEAD → Entry blocked")
        print("="*70)
        
        self.mock_feed.set_status('DEAD', '50 tokens dead')
        
        # Entry order should be BLOCKED
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        self.assertFalse(allowed, "Entry should be blocked on DEAD feed")
        self.assertIn('DEAD', reason)
        print(f"✓ Entry blocked: {reason}")
    
    def test_06_feed_dead_exit_blocked(self):
        """Test Case 3b: Feed DEAD → Exit blocked"""
        print("\n" + "="*70)
        print("TEST 3b: Feed DEAD → Exit blocked")
        print("="*70)
        
        self.mock_feed.set_status('DEAD', '50 tokens dead')
        
        # Exit order should also be BLOCKED when DEAD
        allowed, reason = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='SELL',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=False
        )
        
        self.assertFalse(allowed, "Exit should be blocked on DEAD feed")
        self.assertIn('DEAD', reason)
        print(f"✓ Exit blocked: {reason}")
    
    def test_07_feed_recovery_orders_allowed(self):
        """Test Case 4: Feed recovers → Orders allowed again"""
        print("\n" + "="*70)
        print("TEST 4: Feed recovery → Orders allowed again")
        print("="*70)
        
        # Start with DEAD
        self.mock_feed.set_status('DEAD', '50 tokens dead')
        allowed, _ = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        self.assertFalse(allowed)
        print("✓ Confirmed: Orders blocked on DEAD feed")
        
        # Recovery to OK
        self.mock_feed.set_status('OK', 'All tokens receiving ticks')
        allowed, _ = self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        self.assertTrue(allowed)
        print("✓ Orders allowed after feed recovery")
        print(f"✓ Recovery notification sent: {any('RECOVERED' in m for m in self.mock_notifier.messages)}")
    
    def test_08_notifier_state_changes(self):
        """Test state change notifications"""
        print("\n" + "="*70)
        print("TEST 8: Notifier state changes")
        print("="*70)
        
        initial_count = len(self.mock_notifier.messages)
        
        # Trigger state change to CRITICAL
        self.mock_feed.set_status('CRITICAL', '3 critical tokens')
        self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        # Allow async thread to complete
        time.sleep(0.1)
        
        # Check notification was sent
        self.assertGreater(len(self.mock_notifier.messages), initial_count)
        print(f"✓ Notification on state change: {self.mock_notifier.messages[-1]}")
        
        # Same state should not trigger another alert
        same_state_count = len(self.mock_notifier.messages)
        self.gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        time.sleep(0.1)
        
        self.assertEqual(len(self.mock_notifier.messages), same_state_count)
        print(f"✓ No duplicate notification for same state")
    
    def test_09_infer_is_entry_no_position(self):
        """Test is_entry inference with no position"""
        print("\n" + "="*70)
        print("TEST 9: Infer is_entry - no position")
        print("="*70)
        
        positions = {}
        
        is_entry = ExecutionGateway.infer_is_entry(
            symbol='NIFTY',
            transaction_type='BUY',
            positions=positions
        )
        
        self.assertTrue(is_entry, "Should infer entry when no position exists")
        print("✓ Correctly inferred entry (no position)")
    
    def test_10_infer_is_entry_with_position(self):
        """Test is_entry inference with existing position"""
        print("\n" + "="*70)
        print("TEST 10: Infer is_entry - with position")
        print("="*70)
        
        positions = {
            'NIFTY': {'qty': 1, 'avg_price': 17000.0, 'side': 'LONG'}
        }
        
        is_entry = ExecutionGateway.infer_is_entry(
            symbol='NIFTY',
            transaction_type='SELL',
            positions=positions
        )
        
        self.assertFalse(is_entry, "Should infer exit when position exists")
        print("✓ Correctly inferred exit (position exists)")
    
    def test_11_infer_is_entry_zero_position(self):
        """Test is_entry inference with zero quantity position"""
        print("\n" + "="*70)
        print("TEST 11: Infer is_entry - zero position")
        print("="*70)
        
        positions = {
            'NIFTY': {'qty': 0, 'avg_price': 0.0}
        }
        
        is_entry = ExecutionGateway.infer_is_entry(
            symbol='NIFTY',
            transaction_type='BUY',
            positions=positions
        )
        
        self.assertTrue(is_entry, "Should infer entry when quantity is zero")
        print("✓ Correctly inferred entry (zero qty)")
    
    def test_12_thread_safety(self):
        """Test thread safety of feed health checks"""
        print("\n" + "="*70)
        print("TEST 12: Thread safety")
        print("="*70)
        
        results = []
        errors = []
        
        def change_feed_status():
            """Simulate feed status changes"""
            for i in range(5):
                statuses = ['OK', 'DEGRADED', 'CRITICAL', 'OK']
                self.mock_feed.set_status(statuses[i % len(statuses)], 'test')
                time.sleep(0.01)
        
        def validate_orders():
            """Simulate order validation"""
            try:
                for i in range(10):
                    allowed, reason = self.gateway.validate_order(
                        symbol='NIFTY',
                        transaction_type='BUY',
                        quantity=1,
                        price=17000.0,
                        order_type='MARKET',
                        is_entry=True
                    )
                    results.append(allowed)
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)
        
        # Run concurrent operations
        threads = [
            threading.Thread(target=change_feed_status),
            threading.Thread(target=validate_orders),
            threading.Thread(target=validate_orders),
        ]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have no errors
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")
        print(f"✓ 20 concurrent validations completed without errors")
        print(f"✓ Results counted: {len(results)}")
    
    def test_13_existing_validations_preserved(self):
        """Test that existing validations still work"""
        print("\n" + "="*70)
        print("TEST 13: Existing validations preserved")
        print("="*70)
        
        # Feed is OK
        self.mock_feed.set_status('OK', 'All tokens receiving ticks')
        
        # Invalid quantity should still be blocked
        with patch('config.Config.ENABLE_ORDER_VALIDATION', True):
            allowed, reason = self.gateway.validate_order(
                symbol='NIFTY',
                transaction_type='BUY',
                quantity=0,
                price=17000.0,
                order_type='MARKET',
                is_entry=False
            )
            
            self.assertFalse(allowed)
            self.assertIn('quantity', reason.lower())
            print(f"✓ Invalid quantity still blocked: {reason}")
    
    def test_14_feed_not_configured(self):
        """Test behavior when feed is not configured"""
        print("\n" + "="*70)
        print("TEST 14: Feed not configured")
        print("="*70)
        
        gateway = ExecutionGateway()
        # Don't set feed
        
        # Should allow orders (no feed checks)
        allowed, reason = gateway.validate_order(
            symbol='NIFTY',
            transaction_type='BUY',
            quantity=1,
            price=17000.0,
            order_type='MARKET',
            is_entry=True
        )
        
        self.assertTrue(allowed, "Should allow when feed not configured")
        print("✓ Orders allowed when feed not configured")


class TestFeedCircuitBreakerIntegration(unittest.TestCase):
    """Integration tests with realistic scenarios"""
    
    def setUp(self):
        """Setup for integration tests"""
        self.gateway = ExecutionGateway()
        self.mock_feed = MockFeed()
        self.gateway.set_feed(self.mock_feed)
    
    def test_realistic_trading_scenario(self):
        """Test realistic trading with feed degradation"""
        print("\n" + "="*70)
        print("INTEGRATION: Realistic trading scenario")
        print("="*70)
        
        # Phase 1: Normal trading
        print("Phase 1: Feed healthy, trading normal")
        self.mock_feed.set_status('OK', 'All tokens healthy')
        
        for i in range(3):
            allowed, _ = self.gateway.validate_order(
                symbol=f'TOKEN{i}',
                transaction_type='BUY',
                quantity=1,
                price=100.0,
                order_type='MARKET',
                is_entry=True
            )
            self.assertTrue(allowed)
        print("✓ Entry orders allowed (3 entries)")
        
        # Phase 2: Feed degradation
        print("\nPhase 2: Feed degradation")
        self.mock_feed.set_status('DEGRADED', 'Some tokens slow')
        
        allowed, _ = self.gateway.validate_order(
            symbol='TOKEN0',
            transaction_type='SELL',
            quantity=1,
            price=100.0,
            order_type='MARKET',
            is_entry=False
        )
        self.assertTrue(allowed)
        print("✓ Exit orders still allowed")
        
        # Phase 3: Feed becomes critical
        print("\nPhase 3: Feed critical")
        self.mock_feed.set_status('CRITICAL', '5 critical tokens')
        
        allowed, reason = self.gateway.validate_order(
            symbol='TOKEN1',
            transaction_type='BUY',
            quantity=1,
            price=100.0,
            order_type='MARKET',
            is_entry=True
        )
        self.assertFalse(allowed)
        print(f"✓ New entries blocked: {reason}")
        
        allowed, _ = self.gateway.validate_order(
            symbol='TOKEN1',
            transaction_type='SELL',
            quantity=1,
            price=100.0,
            order_type='MARKET',
            is_entry=False
        )
        self.assertTrue(allowed)
        print("✓ Exit orders still allowed")
        
        # Phase 4: Recovery
        print("\nPhase 4: Feed recovery")
        self.mock_feed.set_status('OK', 'All tokens healthy')
        
        allowed, _ = self.gateway.validate_order(
            symbol='TOKEN2',
            transaction_type='BUY',
            quantity=1,
            price=100.0,
            order_type='MARKET',
            is_entry=True
        )
        self.assertTrue(allowed)
        print("✓ Trading resumed after recovery")


def run_all_tests():
    """Run all tests with formatted output"""
    print("\n" + "="*70)
    print("FEED CIRCUIT BREAKER TEST SUITE")
    print("="*70)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all tests
    suite.addTests(loader.loadTestsFromTestCase(TestFeedCircuitBreaker))
    suite.addTests(loader.loadTestsFromTestCase(TestFeedCircuitBreakerIntegration))
    
    # Run with detailed output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
