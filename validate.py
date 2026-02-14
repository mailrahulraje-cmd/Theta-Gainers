#!/usr/bin/env python3
"""
System Validation Script
Checks if the trading system is properly configured and all components are working.
"""
import os
import sys
from pathlib import Path
import importlib.util

# --------------------------
# Set ROOT_PATH to trading_system folder
# --------------------------
ROOT_PATH = Path(__file__).resolve().parent  # trading_system folder
os.chdir(ROOT_PATH)  # Change working directory to root
sys.path.insert(0, str(ROOT_PATH))  # Add root to Python path

def print_header(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def check_file_exists(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print(f"   {description}: {filepath}")
        return True
    else:
        print(f"   {description} MISSING: {filepath}")
        return False

def check_import(module_name):
    """Check if a module can be imported"""
    try:
        importlib.import_module(module_name)
        print(f"   {module_name}")
        return True
    except ImportError as e:
        print(f"   {module_name} - {e}")
        return False

def main():
    print_header("TRADING SYSTEM VALIDATION")
    
    errors = []
    warnings = []
    
    # Check Python version
    print_header("Python Version")
    version = sys.version_info
    print(f"  Python {version.major}.{version.minor}.{version.micro}")
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        errors.append("Python 3.10+ required")
        print(f"   Python 3.10+ required (you have {version.major}.{version.minor})")
    else:
        print(f"   Version OK")
    
    # Check core files
    print_header("Core System Files")
    core_files = {
        'main.py': 'Main entry point',
        'config.py': 'Configuration',
        'contract.py': 'Type definitions',
        'paper_broker.py': 'Paper broker',
        'live_broker.py': 'Live broker',
    }
    
    for filepath, desc in core_files.items():
        if not check_file_exists(filepath, desc):
            errors.append(f"Missing {filepath}")
    
    # Check module directories
    print_header("Module Directories")
    modules = ['utils', 'core', 'strategy']
    
    for module in modules:
        if os.path.isdir(module):
            init_file = os.path.join(module, '__init__.py')
            if os.path.exists(init_file):
                print(f"   {module}/ (with __init__.py)")
            else:
                print(f"    {module}/ (missing __init__.py)")
                warnings.append(f"{module}/__init__.py missing")
        else:
            print(f"   {module}/ directory missing")
            errors.append(f"Missing {module}/ directory")
    
    # Check dependencies
    print_header("Python Dependencies")
    import_checks = {
        'SmartApi': 'smartapi-python',
        'dotenv': 'python-dotenv',
        'pyotp': 'pyotp',
        'telegram': 'python-telegram-bot',
        'ntplib': 'ntplib',
    }
    
    for module, package in import_checks.items():
        if not check_import(module):
            errors.append(f"Missing dependency: {package}")
    
    # Check configuration files
    print_header("Configuration Files")
    
    if check_file_exists('.env', 'Environment config'):
        print("    Reading .env configuration...")
        from dotenv import load_dotenv
        load_dotenv()
        
        required_vars = {
            'DATA_MODE': 'Data source mode',
            'TRADING_MODE': 'Trading execution mode',
        }
        
        for var, desc in required_vars.items():
            value = os.getenv(var)
            if value:
                print(f"   {var}={value}")
            else:
                print(f"    {var} not set (will use default)")
                warnings.append(f"{var} not configured")
    else:
        print("    .env file not found")
        print("    Copy .env.example to .env and configure")
        warnings.append(".env file missing")
    
    if not check_file_exists('.env.example', 'Example config'):
        warnings.append(".env.example missing")
    
    # Check instruments CSV
    print_header("Market Data Files")
    if not check_file_exists('angel_master_instruments.csv', 'Instruments CSV'):
        errors.append("Instruments CSV missing - download from Angel One")
        print("    Download from Angel One API documentation")
    
    # Check optional files
    print_header("Optional Files")
    optional_files = {
        'README.md': 'Documentation',
        'QUICKSTART.md': 'Quick start guide',
        'requirements.txt': 'Dependencies list',
    }
    
    for filepath, desc in optional_files.items():
        check_file_exists(filepath, desc)
    
    # Load config dynamically
    print_header("Configuration Validation")
    try:
        spec = importlib.util.spec_from_file_location(
            "Config", os.path.join(ROOT_PATH, "config.py")
        )
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        Config = getattr(config_module, "Config")
        
        print(f"   Config module loaded")
        print(f"   DATA_MODE: {Config.DATA_MODE}")
        print(f"   TRADING_MODE: {Config.TRADING_MODE}")
        print(f"   LOTS: {Config.LOTS}")
        
        if Config.TRADING_MODE.upper() == "LIVE":
            print(f"    LIVE TRADING ENABLED - REAL MONEY AT RISK")
            creds = [
                ('API_KEY', Config.API_KEY),
                ('CLIENT_CODE', Config.CLIENT_CODE),
                ('PASSWORD', Config.PASSWORD),
                ('TOTP_SECRET', Config.TOTP_SECRET),
            ]
            missing_creds = [name for name, value in creds if not value]
            for name in missing_creds:
                print(f"   ANGEL_{name} not configured")
            if missing_creds:
                errors.append(f"Missing credentials for LIVE mode: {', '.join(missing_creds)}")
        else:
            print(f"   PAPER TRADING MODE - Safe for testing")
    
    except Exception as e:
        print(f"   Failed to load config: {e}")
        errors.append(f"Config import failed: {e}")
    
    # Summary
    print_header("VALIDATION SUMMARY")
    if errors:
        print(f"\n   {len(errors)} ERROR(S) FOUND:\n")
        for i, error in enumerate(errors, 1):
            print(f"    {i}. {error}")
        print("\n    SYSTEM NOT READY - Fix errors before running")
        return 1
    elif warnings:
        print(f"\n    {len(warnings)} WARNING(S):\n")
        for i, warning in enumerate(warnings, 1):
            print(f"    {i}. {warning}")
        print("\n   SYSTEM READY (with warnings)")
        print("    Warnings are optional but recommended to fix")
        return 0
    else:
        print("\n   ALL CHECKS PASSED")
        print("   SYSTEM READY TO RUN")
        print("\n  Next steps:")
        print("    1. Review configuration in .env")
        print("    2. Test in PAPER mode first: python main.py")
        print("    3. Check QUICKSTART.md for detailed guide")
        return 0

if __name__ == "__main__":
    sys.exit(main())
