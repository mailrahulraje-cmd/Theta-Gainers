"""Standalone runner for the network hardening tests.

This allows running the new tests without pytest installed.
"""
import importlib
import sys

MODULE = 'test_live_network_hardening'


def run():
    mod = importlib.import_module(MODULE)
    failures = []
    total = 0
    for name in dir(mod):
        if name.startswith('test_'):
            total += 1
            func = getattr(mod, name)
            try:
                func()
                print(f"PASS: {name}")
            except AssertionError as e:
                print(f"FAIL: {name} - AssertionError: {e}")
                failures.append((name, e))
            except Exception as e:
                print(f"ERROR: {name} - Exception: {e}")
                failures.append((name, e))

    print(f"\nSummary: {total - len(failures)}/{total} tests passed")
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    run()
