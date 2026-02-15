#!/usr/bin/env python3
"""Verify critical dependencies are installed"""
import sys

print("\n" + "="*70)
print("DEPENDENCIES VERIFICATION")
print("="*70)

required_packages = {
    'requests': 'HTTP library for Telegram API',
    'pyotp': '2FA token generation',
    'websocket-client': 'WebSocket connectivity',
    'pandas': 'Data processing',
}

optional_packages = {
    'emoji': 'Emoji rendering (enhanced support)',
    'python-telegram-bot': 'Alternative Telegram client'
}

print("\n✅ REQUIRED PACKAGES:")
print("-" * 70)

all_ok = True
for pkg, description in required_packages.items():
    try:
        __import__(pkg.replace('-', '_'))
        print(f"  ✅ {pkg:25} {description}")
    except ImportError:
        print(f"  ❌ {pkg:25} NOT INSTALLED - {description}")
        all_ok = False

print("\n⚠️  OPTIONAL PACKAGES (for enhanced emoji support):")
print("-" * 70)

for pkg, description in optional_packages.items():
    try:
        __import__(pkg.replace('-', '_'))
        print(f"  ✅ {pkg:25} {description}")
    except ImportError:
        print(f"  ⚠️  {pkg:25} NOT INSTALLED (optional) - {description}")

# Python version check
print("\n✅ PYTHON VERSION:")
print("-" * 70)
print(f"  ✅ Python {sys.version.split()[0]} ({'UTF-8 capable' if sys.stdout.encoding.upper() in ['UTF-8', 'UTF-16'] or 'utf' in sys.stdout.encoding.lower() else 'ASCII mode - may have emoji issues'})")

# UTF-8 encoding check
print("\n✅ UTF-8 ENCODING:")
print("-" * 70)
print(f"  ✅ stdout encoding: {sys.stdout.encoding}")
print(f"  ✅ stdin encoding: {sys.stdin.encoding}")

# Test emoji rendering
print("\n✅ EMOJI RENDERING TEST:")
print("-" * 70)
test_emojis = {
    '🚀': 'Rocket (system startup)',
    '✅': 'Checkmark (success)',
    '⚠️': 'Warning',
    '📞': 'Call (CE)',
    '📧': 'Email (PE)',
    '🟦': 'Blue square (buy)',
    '🟥': 'Red square (sell)',
    '📈': 'Profit',
    '📉': 'Loss',
    '🔒': 'Locked leg',
    '💓': 'Heartbeat',
    '₹': 'Rupee'
}

for emoji, desc in test_emojis.items():
    try:
        print(f"  ✅ {emoji} - {desc}")
    except Exception as e:
        print(f"  ❌ Cannot render '{desc}' - {e}")

if all_ok:
    print("\n" + "="*70)
    print("✅ ALL REQUIRED DEPENDENCIES INSTALLED - READY FOR DEPLOYMENT")
    print("="*70 + "\n")
    sys.exit(0)
else:
    print("\n" + "="*70)
    print("❌ MISSING REQUIRED PACKAGES - INSTALL WITH:")
    print("   pip install --upgrade requests pyotp websocket-client pandas emoji")
    print("="*70 + "\n")
    sys.exit(1)
