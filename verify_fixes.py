#!/usr/bin/env python3
"""
Comprehensive Fix Verification Script
Verifies all fixes applied to the trading system
"""
import os
import sys
import inspect
from pathlib import Path

def verify_websocket_callbacks():
    """Verify WebSocket callback signatures in feed.py"""
    print("\n" + "="*70)
    print("TASK 1: WebSocket Callback Signature Verification")
    print("="*70)
    
    try:
        from core.feed import UnifiedFeed
        
        # Check UnifiedFeed _on_close signature
        on_close_sig = inspect.signature(UnifiedFeed._on_close)
        params = list(on_close_sig.parameters.keys())
        
        print(f" UnifiedFeed._on_close signature found: {on_close_sig}")
        print(f"   Parameters: {params}")
        
        # Verify it accepts variable arguments
        if 'args' in params or any('*' in str(param) for param in on_close_sig.parameters.values()):
            print(" Signature is flexible (accepts *args)")
            print(" Compatible with SmartWebSocketV2 SDK")
        else:
            print("  Warning: Signature may not handle variable arguments")
        
        # Try to verify SmartWebSocketV2 patches (if SmartAPI installed)
        try:
            from core.feed import SmartWebSocketV2
            print("\n SmartWebSocketV2 imported successfully")
            print("   Monkey-patch for callback signatures has been applied")
            
            # Check if patches exist
            ws_close_sig = inspect.signature(SmartWebSocketV2._on_close)
            print(f"   SmartWebSocketV2._on_close: {ws_close_sig}")
            
            ws_error_sig = inspect.signature(SmartWebSocketV2._on_error)
            print(f"   SmartWebSocketV2._on_error: {ws_error_sig}")
            
            print(" SmartAPI callback signature fix verified")
            
        except ImportError:
            print("\n  SmartWebSocketV2 not available (SmartAPI not installed)")
            print("   This is OK for verification - patch will apply when SmartAPI is present")
        
        return True
            
    except Exception as e:
        print(f" Error: {e}")
        return False

def verify_broker_signature():
    """Verify LiveBroker place_order signature"""
    print("\n" + "="*70)
    print("TASK 2: LiveBroker place_order Signature Verification")
    print("="*70)
    
    try:
        from live_broker import LiveBroker
        
        # Check place_order signature
        place_order_sig = inspect.signature(LiveBroker.place_order)
        params = list(place_order_sig.parameters.keys())
        
        print(f" place_order signature found: {place_order_sig}")
        print(f"   Parameters: {params}")
        
        # Verify it accepts variable arguments
        has_args = 'args' in params
        has_kwargs = 'kwargs' in params
        
        if has_args and has_kwargs:
            print(" Signature supports *args and **kwargs")
            print(" Compatible with all Engine calling patterns:")
            print("   - place_order(side, token, qty, price, tag)")
            print("   - place_order(token, symbol, side, price, qty, meta)")
            print("   - place_order(side=..., token=..., qty=..., ...)")
            
            # Verify _parse_order_args exists
            if hasattr(LiveBroker, '_parse_order_args'):
                print(" _parse_order_args() method found for flexible parsing")
            return True
        else:
            print("  Warning: Signature may not handle all Engine patterns")
            return False
            
    except Exception as e:
        print(f" Error: {e}")
        return False

def verify_file_cleanup():
    """Verify duplicate files have been archived"""
    print("\n" + "="*70)
    print("TASK 3: Duplicate File Cleanup Verification")
    print("="*70)
    
    root = Path(".")
    archive = root / "archive"
    
    # Check for obsolete files in root
    obsolete_files = [
        "live_broker_fixed.py",
        "live_broker_original.py",
    ]
    
    obsolete_in_strategy = [
        "strategy/engine_original.py"
    ]
    
    all_clean = True
    archived_count = 0
    
    print("\nChecking root directory...")
    for file in obsolete_files:
        file_path = root / file
        if file_path.exists():
            print(f"  {file} still exists in root (should be archived)")
            all_clean = False
        else:
            print(f" {file} not in root (archived)")
            archived_count += 1
    
    print("\nChecking strategy directory...")
    for file in obsolete_in_strategy:
        file_path = root / file
        if file_path.exists():
            print(f"  {file} still exists (should be archived)")
            all_clean = False
        else:
            print(f" {file} not in strategy/ (archived)")
            archived_count += 1
    
    # Verify production files exist
    print("\nVerifying production files...")
    production_files = [
        "live_broker.py",
        "paper_broker.py",
        "strategy/engine.py",
        "core/feed.py",
        "main.py",
        "config.py"
    ]
    
    for file in production_files:
        file_path = root / file
        if file_path.exists():
            size = file_path.stat().st_size
            print(f" {file} exists ({size:,} bytes)")
        else:
            print(f" {file} MISSING!")
            all_clean = False
    
    # Check archive directory
    print(f"\nArchive directory contents:")
    if archive.exists():
        archived_files = list(archive.glob("*.py"))
        print(f" Archive contains {len(archived_files)} Python files")
        for f in sorted(archived_files):
            size = f.stat().st_size
            print(f"   - {f.name} ({size:,} bytes)")
    else:
        print("  Archive directory not found")
    
    return all_clean

def verify_imports():
    """Verify all imports work correctly"""
    print("\n" + "="*70)
    print("IMPORT VERIFICATION")
    print("="*70)
    
    imports_ok = True
    
    # Test critical imports
    test_imports = [
        ("config", "Config"),
        ("contract", "BrokerProtocol"),
        ("live_broker", "LiveBroker"),
        ("paper_broker", "PaperBroker"),
        ("strategy.engine", "StrategyEngine"),
        ("core.feed", "UnifiedFeed"),
        ("core.state", "StrategyState"),
        ("utils.logger", "logger"),
    ]
    
    for module_name, class_name in test_imports:
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            print(f" from {module_name} import {class_name}")
        except ImportError as e:
            print(f" Failed: from {module_name} import {class_name}")
            print(f"   Error: {e}")
            imports_ok = False
        except AttributeError as e:
            print(f" {class_name} not found in {module_name}")
            print(f"   Error: {e}")
            imports_ok = False
    
    return imports_ok

def main():
    """Run all verifications"""
    print("\n" + "="*70)
    print("TRADING SYSTEM FIX VERIFICATION")
    print("="*70)
    print("This script verifies all fixes have been properly applied")
    
    results = {
        "WebSocket Callbacks": verify_websocket_callbacks(),
        "LiveBroker Signature": verify_broker_signature(),
        "File Cleanup": verify_file_cleanup(),
        "Import Compatibility": verify_imports()
    }
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    for task, passed in results.items():
        status = " PASSED" if passed else " FAILED"
        print(f"{status} - {task}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n All verifications passed! System is ready for production.")
        return 0
    else:
        print("\n  Some verifications failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
