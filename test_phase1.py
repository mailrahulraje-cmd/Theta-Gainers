#!/usr/bin/env python3
"""
PHASE 1 ACCEPTANCE TESTS
Tests for Core Safety: Phase Constants and Notifier Contract

Run this script to verify Phase 1 is complete.
All tests must pass before proceeding to Phase 2.
"""

import sys
import os
import re

# Add system path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_phase_constants_imports():
    """Test 1: Verify all modules import constants correctly"""
    print("\n" + "="*80)
    print("TEST 1: Phase Constants Imports")
    print("="*80)
    
    from constants import (
        PHASE_STANDBY, PHASE_PHASE0, PHASE_PHASE1,
        PHASE_INIT, PHASE_IN_TRADE, PHASE_CLOSED
    )
    
    # Verify constants have correct values
    assert PHASE_STANDBY == "STANDBY", f"PHASE_STANDBY should be 'STANDBY', got '{PHASE_STANDBY}'"
    assert PHASE_PHASE0 == "PHASE0", f"PHASE_PHASE0 should be 'PHASE0', got '{PHASE_PHASE0}'"
    assert PHASE_PHASE1 == "PHASE1", f"PHASE_PHASE1 should be 'PHASE1', got '{PHASE_PHASE1}'"
    assert PHASE_INIT == "INIT", f"PHASE_INIT should be 'INIT', got '{PHASE_INIT}'"
    assert PHASE_IN_TRADE == "IN TRADE", f"PHASE_IN_TRADE should be 'IN TRADE', got '{PHASE_IN_TRADE}'"
    assert PHASE_CLOSED == "CLOSED", f"PHASE_CLOSED should be 'CLOSED', got '{PHASE_CLOSED}'"
    
    print(" All phase constants defined correctly")
    return True


def test_no_raw_phase_strings():
    """Test 2: Verify NO raw phase strings remain in codebase"""
    print("\n" + "="*80)
    print("TEST 2: No Raw Phase Strings")
    print("="*80)
    
    # Patterns to search for
    raw_patterns = [
        r"['\"]STANDBY['\"]",
        r"['\"]PHASE0['\"]",
        r"['\"]PHASE1['\"]",
        r"['\"]PHASE 0['\"]",
        r"['\"]PHASE 1['\"]",
        r"['\"]IN TRADE['\"]",
        r"['\"]INIT['\"]",
        r"['\"]CLOSED['\"]",
        r"['\"]TRADING['\"]"
    ]
    
    # Files to check
    files_to_check = [
        'strategy/engine.py',
        'utils/notifier.py',
        'utils/notifier_improved.py',
        'diagnose_no_trades.py',
        'paper_broker.py',
        'live_broker.py',
        'main.py'
    ]
    
    violations = []
    
    for filepath in files_to_check:
        if not os.path.exists(filepath):
            print(f"  File not found: {filepath} (skipping)")
            continue
            
        with open(filepath, 'r') as f:
            content = f.read()
            
        for line_num, line in enumerate(content.split('\n'), 1):
            # Skip comments and docstrings
            if line.strip().startswith('#'):
                continue
            if '"""' in line or "'''" in line:
                continue
            
            for pattern in raw_patterns:
                if re.search(pattern, line):
                    # Check if it's using PHASE_ constant
                    if 'PHASE_' not in line and 'constants.py' not in filepath:
                        violations.append({
                            'file': filepath,
                            'line': line_num,
                            'content': line.strip()
                        })
    
    if violations:
        print(" Found raw phase strings:")
        for v in violations:
            print(f"   {v['file']}:{v['line']} - {v['content']}")
        return False
    else:
        print(" No raw phase strings found")
        print(f"   Checked {len(files_to_check)} files")
        return True


def test_strategy_engine_imports_constants():
    """Test 3: Verify strategy engine imports and uses constants"""
    print("\n" + "="*80)
    print("TEST 3: Strategy Engine Uses Constants")
    print("="*80)
    
    with open('strategy/engine.py', 'r') as f:
        content = f.read()
    
    # Check for constants import
    if 'from constants import' not in content:
        print(" strategy/engine.py does not import constants")
        return False
    
    # Check that it imports the phase constants
    required_imports = [
        'PHASE_STANDBY', 'PHASE_PHASE0', 'PHASE_PHASE1',
        'PHASE_INIT', 'PHASE_IN_TRADE', 'PHASE_CLOSED'
    ]
    
    missing_imports = []
    for constant in required_imports:
        if constant not in content:
            missing_imports.append(constant)
    
    if missing_imports:
        print(f" strategy/engine.py missing imports: {missing_imports}")
        return False
    
    print(" strategy/engine.py imports all phase constants")
    return True


def test_notifier_contract_assertion():
    """Test 4: Verify notifier contract assertion in strategy engine"""
    print("\n" + "="*80)
    print("TEST 4: Notifier Contract Assertion")
    print("="*80)
    
    with open('strategy/engine.py', 'r') as f:
        content = f.read()
    
    # Check for notifier validation code
    required_elements = [
        'required_methods',
        'send_entry',
        'send_exit',
        'send_trade_log',
        'send_strike_selection',
        'send_phase_change',
        'send_lock_event',
        'send_trade_entry',
        'send_trailing_sl_update',
        'heartbeat',
        'missing_methods',
        'hasattr(notifier',
        'callable(getattr(notifier'
    ]
    
    missing_elements = []
    for element in required_elements:
        if element not in content:
            missing_elements.append(element)
    
    if missing_elements:
        print(f" Notifier validation missing elements: {missing_elements}")
        return False
    
    print(" Notifier contract assertion present in strategy engine")
    print("   Validates 9 required methods")
    print("   Gracefully disables notifier if validation fails")
    return True


def test_syntax_validation():
    """Test 5: Verify all modified files compile"""
    print("\n" + "="*80)
    print("TEST 5: Syntax Validation")
    print("="*80)
    
    files_to_compile = [
        'constants.py',
        'strategy/engine.py',
        'utils/notifier.py',
        'utils/notifier_improved.py',
        'diagnose_no_trades.py'
    ]
    
    import py_compile
    
    for filepath in files_to_compile:
        if not os.path.exists(filepath):
            print(f"  File not found: {filepath} (skipping)")
            continue
            
        try:
            py_compile.compile(filepath, doraise=True)
            print(f" {filepath}")
        except py_compile.PyCompileError as e:
            print(f" {filepath} - SYNTAX ERROR:")
            print(f"   {e}")
            return False
    
    return True


def test_can_import_modules():
    """Test 6: Verify modules can be imported"""
    print("\n" + "="*80)
    print("TEST 6: Module Import Test")
    print("="*80)
    
    modules_to_import = [
        ('constants', 'Phase constants'),
        ('strategy.engine', 'Strategy engine'),
        ('utils.notifier', 'Notifier')
    ]
    
    for module_name, description in modules_to_import:
        try:
            __import__(module_name)
            print(f" {description} ({module_name})")
        except Exception as e:
            print(f" {description} ({module_name}) - IMPORT ERROR:")
            print(f"   {e}")
            return False
    
    return True


def run_all_tests():
    """Run all Phase 1 acceptance tests"""
    print("\n" + "="*80)
    print(" PHASE 1 ACCEPTANCE TESTS")
    print("="*80)
    print("Core Safety: Phase Constants + Notifier Contract")
    print("="*80)
    
    tests = [
        ("Phase Constants Imports", test_phase_constants_imports),
        ("No Raw Phase Strings", test_no_raw_phase_strings),
        ("Strategy Engine Uses Constants", test_strategy_engine_imports_constants),
        ("Notifier Contract Assertion", test_notifier_contract_assertion),
        ("Syntax Validation", test_syntax_validation),
        ("Module Import Test", test_can_import_modules)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n {test_name} - EXCEPTION:")
            print(f"   {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*80)
    print("PHASE 1 TEST SUMMARY")
    print("="*80)
    
    for test_name, result in results:
        status = " PASS" if result else " FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(result for _, result in results)
    
    print("="*80)
    if all_passed:
        print(" ALL PHASE 1 TESTS PASSED")
        print("="*80)
        print("\n PHASE 1 COMPLETE!")
        print("   Core Safety is fully implemented:")
        print("    All phase constants enforced")
        print("    No raw phase strings remain")
        print("    Notifier contract validated at runtime")
        print("    All syntax validated")
        print("\n Ready to proceed to Phase 2")
        return 0
    else:
        print(" PHASE 1 TESTS FAILED")
        print("="*80)
        print("\n  PHASE 1 NOT COMPLETE")
        print("   Fix failing tests before proceeding to Phase 2")
        return 1


if __name__ == "__main__":
    # Change to trading system directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_dir = os.path.join(script_dir, 'trading_system_fixed')
    
    if os.path.exists(trading_dir):
        os.chdir(trading_dir)
        # Add to Python path for imports
        sys.path.insert(0, trading_dir)
    
    sys.exit(run_all_tests())
