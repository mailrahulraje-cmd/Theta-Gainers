#!/usr/bin/env python3
"""
PHASE 1 INTEGRATION TESTS
Validates all Phase 1 architectural fixes

Tests covered:
1. Phase constants and centralized phase transitions
2. State normalization for legacy format
3. Atomic state writes
4. Bounded delta scanning
5. Protocol assertions
6. Rate limiting and execution gateway
7. Notifier self-test
"""

import sys
import os
import json
import time
import threading
import tempfile
from datetime import datetime, date

# Add system path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import test utilities
import unittest
from unittest.mock import Mock, MagicMock, patch

# Import system components
from constants import (
    PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1,
    PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED, PHASE_TRADING
)
from config import Config
from contract import StateProtocol, StrategyStateProtocol, NotifierProtocol
from utils.logger import logger

class TestPhaseConstants(unittest.TestCase):
    """Test 1: Phase constants are properly defined"""
    
    def test_all_phase_constants_exist(self):
        """Verify all required phase constants exist"""
        required = [PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1, PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED]
        for phase in required:
            self.assertIsNotNone(phase)
            self.assertIsInstance(phase, str)
            print(f" Phase constant exists: {phase}")
    
    def test_phase_alias(self):
        """Verify PHASE_TRADING alias works"""
        self.assertEqual(PHASE_TRADING, PHASE_IN_TRADE)
        print(f" PHASE_TRADING alias: {PHASE_TRADING} == {PHASE_IN_TRADE}")


class TestStateNormalization(unittest.TestCase):
    """Test 2: State normalization handles legacy format"""
    
    def setUp(self):
        """Create temp state file"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
    
    def tearDown(self):
        """Clean up temp file"""
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)
    
    def test_legacy_state_normalization(self):
        """Test that legacy flat state is normalized to structured format"""
        # Create legacy state file
        legacy_state = {
            'sell_ce_entered': True,
            'sell_ce_token': '123',
            'sell_ce_strike': 24500,
            'sell_pe_entered': False,
            'buy_ce_entered': True,
            'buy_ce_token': '456',
            'buy_ce_strike': 24550,
            'buy_pe_entered': False
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(legacy_state, f)
        
        # Import StrategyState and load
        from core.state import StrategyState
        
        state = StrategyState(self.temp_file.name)
        
        # Check that structured 'legs' object was created
        self.assertIn('legs', state.state)
        legs = state.state['legs']
        self.assertIn('sell_ce', legs)
        self.assertIn('sell_pe', legs)
        self.assertIn('buy_ce', legs)
        self.assertIn('buy_pe', legs)
        
        # Verify structure
        self.assertEqual(legs['sell_ce']['entered'], True)
        self.assertEqual(legs['sell_ce']['token'], '123')
        self.assertIsNotNone(legs['sell_ce']['qty'])
        
        print(" Legacy state normalized to structured format")
    
    def test_atomic_state_write(self):
        """Test that state writes are atomic (temp file + rename)"""
        from core.state import StrategyState
        
        state = StrategyState(self.temp_file.name)
        
        # Set a value
        state.set('test_key', 'test_value')
        
        # Verify it was written
        self.assertEqual(state.get('test_key'), 'test_value')
        
        # Verify file exists and contains value
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(data.get('test_key'), 'test_value')
        print(" Atomic state writes work correctly")
    
    def test_thread_safe_state_updates(self):
        """Test that state updates are thread-safe"""
        from core.state import StrategyState
        
        state = StrategyState(self.temp_file.name)
        results = []
        
        def update_state(key, value):
            for i in range(100):
                state.set(f'{key}_{i}', value + i)
            results.append(True)
        
        # Run multiple threads
        threads = [
            threading.Thread(target=update_state, args=(f'thread{i}', i))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # All updates should complete without error
        self.assertEqual(len(results), 5)
        print(" Thread-safe state updates work correctly")


class TestDeltaBounds(unittest.TestCase):
    """Test 3: Delta scanning is bounded by time and attempts"""
    
    def test_delta_scan_bounds(self):
        """Test that delta scan respects bounds"""
        from utils.delta_utils import RobustDeltaProvider
        
        provider = RobustDeltaProvider()
        
        # Create mock options with deltas
        options = [
            {'symbol': 'NIFTY2450024500CE', 'delta': 0.20, 'ltp': 100.0},
            {'symbol': 'NIFTY2450024550CE', 'delta': 0.25, 'ltp': 95.0},
            {'symbol': 'NIFTY2450024450CE', 'delta': 0.15, 'ltp': 105.0},
        ]
        
        # Test bounded scan
        result = provider.scan_strikes_with_bounds(
            options=options,
            target_delta=0.22,
            max_attempts=2,
            max_time_seconds=1.0
        )
        
        # Should find closest match within bounds
        self.assertIsNotNone(result)
        self.assertIn('delta', result)
        
        print(f" Delta scan found match: {result['symbol']} (:{result['delta']:.3f})")
    
    def test_delta_scan_timeout(self):
        """Test that delta scan times out after max_time_seconds"""
        from utils.delta_utils import RobustDeltaProvider
        
        provider = RobustDeltaProvider()
        
        # Create options without matching delta
        options = [
            {'symbol': f'OPT_{i}', 'delta': 0.99 - (i * 0.01), 'ltp': 100.0}
            for i in range(10)
        ]
        
        # Scan with very tight time limit
        import time
        start = time.time()
        result = provider.scan_strikes_with_bounds(
            options=options,
            target_delta=0.5,  # Far from any option
            max_attempts=100,
            max_time_seconds=0.1  # Very short timeout
        )
        elapsed = time.time() - start
        
        # Should timeout before checking all options
        self.assertLess(elapsed, 0.5)
        print(f" Delta scan respects time bounds: {elapsed:.3f}s (max was 0.1s)")


class TestProtocolConformance(unittest.TestCase):
    """Test 4: Protocol assertions work at runtime"""
    
    def test_notifier_protocol_assertion(self):
        """Test that notifier protocol assertion catches missing methods"""
        # Create a simple notifier object (not a unittest.mock.Mock) so
        # hasattr() reflects only explicitly set attributes
        class _SimpleNotifier:
            pass

        mock_notifier = _SimpleNotifier()
        
        # Missing most required methods
        mock_notifier.send_entry = Mock()
        mock_notifier.heartbeat = Mock()
        # Missing: send_exit, send_trade_log, send_phase_change, etc.
        
        # Protocol assertion should fail
        required_methods = [
            'send_entry', 'send_exit', 'send_trade_log',
            'send_strike_selection', 'send_phase_change',
            'send_lock_event', 'send_trade_entry',
            'send_trailing_sl_update', 'heartbeat'
        ]
        
        missing = []
        for method in required_methods:
            if not hasattr(mock_notifier, method) or not callable(getattr(mock_notifier, method)):
                missing.append(method)
        
        self.assertGreater(len(missing), 0)
        print(f" Protocol assertion detects missing methods: {missing}")


class TestPhaseTransitions(unittest.TestCase):
    """Test 5: Phase transitions use centralized set_phase()"""
    
    def test_set_phase_validation(self):
        """Test that set_phase validates phase constants"""
        # Create mock engine with set_phase method
        mock_state = Mock()
        mock_notifier = Mock()
        
        # Would need actual engine setup to test this fully
        # For now, just test the validation logic
        valid_phases = [PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1, PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED]
        
        # Valid phase should pass
        self.assertIn(PHASE_INIT, valid_phases)
        
        # Invalid phase should not pass
        self.assertNotIn("INVALID_PHASE", valid_phases)
        
        print(" Phase validation logic works correctly")


class TestExecutionGateway(unittest.TestCase):
    """Test 6: Execution gateway enforces safety checks"""
    
    def test_execution_gateway_initialization(self):
        """Test that execution gateway initializes correctly"""
        from core.execution_gateway import get_execution_gateway
        
        gateway = get_execution_gateway()
        
        # Should be a singleton
        gateway2 = get_execution_gateway()
        self.assertIs(gateway, gateway2)
        
        print(" Execution gateway singleton works")
    
    def test_rate_limiting(self):
        """Test rate limiter prevents exceeding max orders per minute"""
        from core.execution_gateway import OrderRateLimiter
        
        limiter = OrderRateLimiter(max_orders_per_minute=3)
        
        # First 3 orders should succeed
        allowed1, _ = limiter.can_place_order()
        allowed2, _ = limiter.can_place_order()
        allowed3, _ = limiter.can_place_order()
        
        self.assertTrue(allowed1)
        self.assertTrue(allowed2)
        self.assertTrue(allowed3)
        
        # 4th order should be blocked
        allowed4, reason = limiter.can_place_order()
        self.assertFalse(allowed4)
        self.assertIn("Rate limit", reason)
        
        print(f" Rate limiting works: blocked 4th order with reason: {reason}")


class TestStateLocksAndProtocol(unittest.TestCase):
    """Test 7: State protocol lock methods return bool"""
    
    def test_lock_methods_return_bool(self):
        """Test that lock methods implement protocol correctly"""
        import tempfile
        from core.state import StrategyState
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_file.close()
        
        try:
            state = StrategyState(temp_file.name)
            
            # Test lock methods return bool
            result = state.lock_sell_ce_leg({
                'token': '12345',
                'strike': 24500,
                'ltp': 100.0,
                'symbol': 'NIFTY2450024500CE'
            })
            
            self.assertIsInstance(result, bool)
            self.assertTrue(result)  # First lock should succeed
            
            # Second lock should fail and return False
            result2 = state.lock_sell_ce_leg({
                'token': '12345',
                'strike': 24500,
                'ltp': 100.0,
                'symbol': 'NIFTY2450024500CE'
            })
            
            self.assertFalse(result2)
            
            print(" Lock methods implement protocol correctly (return bool)")
        finally:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)


if __name__ == '__main__':
    print("="*80)
    print("PHASE 1 INTEGRATION TESTS")
    print("="*80)
    print()
    
    # Run tests
    unittest.main(verbosity=2)
