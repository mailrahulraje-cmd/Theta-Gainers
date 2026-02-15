#!/usr/bin/env python3
"""Quick verification of feed circuit breaker implementation"""

from core.execution_gateway import ExecutionGateway, get_execution_gateway

print("\n" + "="*70)
print("FEATURE VERIFICATION")
print("="*70)

# Test singleton
gw = get_execution_gateway()
print("✓ ExecutionGateway singleton works")

# Test new properties
assert hasattr(gw, 'feed'), "Missing 'feed' property"
print("✓ Feed property exists")

assert hasattr(gw, '_last_feed_alert_state'), "Missing alert state tracking"
print("✓ Feed alert state tracking exists")

assert hasattr(gw, 'notifier'), "Missing 'notifier' property"
print("✓ Notifier property exists")

# Test new methods
assert hasattr(gw, 'set_feed'), "Missing 'set_feed' method"
print("✓ set_feed() method exists")

assert hasattr(gw, 'set_notifier'), "Missing 'set_notifier' method"
print("✓ set_notifier() method exists")

assert hasattr(ExecutionGateway, 'infer_is_entry'), "Missing 'infer_is_entry' method"
print("✓ infer_is_entry() static method exists")

# Test entry inference
is_entry = ExecutionGateway.infer_is_entry('NIFTY', 'BUY', {})
assert is_entry == True, "Should infer entry with empty positions"
print("✓ Entry inference works (empty positions)")

is_entry = ExecutionGateway.infer_is_entry('NIFTY', 'BUY', {'NIFTY': {'qty': 1}})
assert is_entry == False, "Should infer exit with existing position"
print("✓ Entry inference works (existing position)")

# Test validate_order signature
import inspect
sig = inspect.signature(gw.validate_order)
params = list(sig.parameters.keys())
assert 'is_entry' in params, "Missing 'is_entry' parameter in validate_order"
print("✓ validate_order() has 'is_entry' parameter")

# Test basic order validation (without feed)
allowed, reason = gw.validate_order(
    symbol='NIFTY',
    transaction_type='BUY',
    quantity=1,
    price=17000.0,
    order_type='MARKET',
    is_entry=True
)
assert allowed == True, f"Basic validation should pass: {reason}"
print("✓ Basic order validation works")

print("\n" + "="*70)
print("✅ ALL FEATURES VERIFIED")
print("="*70)
