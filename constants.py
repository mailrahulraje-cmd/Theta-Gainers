"""
System-wide constants to eliminate string mismatches.
Ensures consistency across all modules.
"""

# Phase Constants - USE THESE EVERYWHERE
PHASE_STANDBY = "STANDBY"
PHASE_PHASE0 = "PHASE0"
PHASE_PHASE1 = "PHASE1"
PHASE_INIT = "INIT"
PHASE_IN_TRADE = "IN TRADE"  # CRITICAL: Matches notifier expectation
PHASE_CLOSED = "CLOSED"

# Legacy compatibility (if needed elsewhere)
PHASE_INIT_COMPLETE = "INIT_COMPLETE"
PHASE_TRADING = PHASE_IN_TRADE  # Alias for backward compatibility
