#!/usr/bin/env python3
"""
TRADELEG V1 USAGE GUIDE & MIGRATION ROADMAP

This document explains:
1. TradeLegV1 architecture and versioning strategy
2. How to use TradeLegV1 in the trading system
3. Future migration path to V2, V3, etc.
4. Data integrity patterns (checksum verification)
"""

# =============================================================================
# 1. TRADELEG V1 OVERVIEW
# =============================================================================

"""
TradeLegV1 is a versioned dataclass that replaces fragile dictionary-based
trade leg storage.

BEFORE (Fragile):
  trade_legs = {
    'sell_ce': {
        'token': '12345',
        'entry_price': 50.0
    }
  }
  # Problems: No validation, no schema, typos cause silent failures

AFTER (Type-Safe):
  from contract import TradeLegV1
  leg = TradeLegV1(
    token='12345',
    entry_price=50.0,
    quantity=1,
    side='SELL',
    timestamp='2025-02-15T09:30:00.000000'
  )
  # Benefits: Full validation, type hints, IDE support, versioning
"""

# =============================================================================
# 2. FIELD DEFINITIONS
# =============================================================================

"""
TradeLegV1 Fields:

REQUIRED (must always be provided):
  - token: str
      Instrument token (e.g., "12345")
      Validation: non-empty string
  
  - entry_price: float
      Entry price of the leg
      Validation: must be > 0
  
  - quantity: int
      Number of contracts
      Validation: must be > 0, must be integer
  
  - side: str
      Trade direction: "SELL" or "BUY"
      Validation: case-insensitive, validates against ["SELL", "BUY"]
  
  - timestamp: str
      ISO 8601 format: "2025-02-15T09:30:00.000000"
      Validation: non-empty string
  
  - version: int (default=1)
      Schema version for future migrations
      Always set to 1 for TradeLegV1

OPTIONAL (for audit trail and PnL tracking):
  - leg_id: str (default="")
      Unique identifier for this leg
  
  - status: str (default="OPEN")
      Leg status: "OPEN", "CLOSED", or "EXITED"
  
  - exit_price: Optional[float] (default=None)
      Exit price if leg is closed
      Validation: must be > 0 if provided
  
  - pnl: Optional[float] (default=None)
      Profit/loss amount if leg is closed
"""

# =============================================================================
# 3. CREATING TRADE LEGS
# =============================================================================

"""
Example 1: Basic Creation
"""
from contract import TradeLegV1
from datetime import datetime

leg = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000"
)
print(f"Created: {leg}")
# Output: TradeLegV1(token='12345', side='SELL', qty=1, entry=50.0, status='OPEN', ts=2025-02-15T09:30:00)


"""
Example 2: With Metadata
"""
leg_with_metadata = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000",
    leg_id="SELL_CE_001",
    status="OPEN"
)


"""
Example 3: Closed Leg with PnL
"""
closed_leg = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000",
    leg_id="SELL_CE_001",
    status="CLOSED",
    exit_price=48.5,
    pnl=150.0  # (50.0 - 48.5) * 1 * 100 rupees per point
)

# =============================================================================
# 4. DESERIALIZATION (from_dict)
# =============================================================================

"""
When loading trade legs from CSV, JSON, or database, use from_dict().
It performs:
  ✓ Version detection
  ✓ Required field validation
  ✓ Type coercion (string → float, etc.)
  ✓ Value validation (entry_price > 0, side in ["SELL", "BUY"], etc.)
  ✓ Clear error messages if validation fails
"""

# Example 1: Valid data (typical case)
data = {
    "token": "12345",
    "entry_price": 50.0,
    "quantity": 1,
    "side": "SELL",
    "timestamp": "2025-02-15T09:30:00.000000"
}
leg = TradeLegV1.from_dict(data)
print(f"Loaded: {leg}")


# Example 2: Data with optional fields
data_full = {
    "token": "12345",
    "entry_price": 50.0,
    "quantity": 1,
    "side": "SELL",
    "timestamp": "2025-02-15T09:30:00.000000",
    "leg_id": "SELL_CE_001",
    "status": "CLOSED",
    "exit_price": 48.5,
    "pnl": 150.0,
    "version": 1
}
leg = TradeLegV1.from_dict(data_full)


# Example 3: Handling errors

# Missing required field
try:
    bad_data = {"token": "12345", "entry_price": 50.0}  # Missing quantity, side, timestamp
    leg = TradeLegV1.from_dict(bad_data)
except KeyError as e:
    print(f"Error: {e}")  # Missing required fields: ['quantity', 'side', 'timestamp']


# Invalid value
try:
    bad_data = {
        "token": "12345",
        "entry_price": -50.0,  # Negative price!
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000"
    }
    leg = TradeLegV1.from_dict(bad_data)
except ValueError as e:
    print(f"Error: {e}")  # entry_price must be > 0, got -50.0


# Future version (incompatible)
try:
    future_data = {
        "token": "12345",
        "entry_price": 50.0,
        "quantity": 1,
        "side": "SELL",
        "timestamp": "2025-02-15T09:30:00.000000",
        "version": 2  # This system doesn't support V2 yet!
    }
    leg = TradeLegV1.from_dict(future_data)
except ValueError as e:
    print(f"Error: {e}")  # Cannot deserialize TradeLegV1 from version 2 data...


# =============================================================================
# 5. SERIALIZATION (to_dict)
# =============================================================================

"""
Convert TradeLegV1 to dictionary for storage (CSV, JSON, database).
Always includes version field.
"""

leg = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000"
)

leg_dict = leg.to_dict()
print(leg_dict)
# Output: {
#   'token': '12345',
#   'entry_price': 50.0,
#   'quantity': 1,
#   'side': 'SELL',
#   'timestamp': '2025-02-15T09:30:00.000000',
#   'version': 1,
#   'leg_id': '',
#   'status': 'OPEN',
#   'exit_price': None,
#   'pnl': None
# }

# Can be saved to CSV:
import csv
with open('trades.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=leg_dict.keys())
    writer.writeheader()
    writer.writerow(leg_dict)

# Or JSON:
import json
with open('trades.json', 'w') as f:
    json.dump([leg.to_dict()], f)


# =============================================================================
# 6. DATA INTEGRITY (Checksums)
# =============================================================================

"""
TradeLegV1 supports SHA256 checksums to detect data corruption.
Use when storing to disk or transferring data.
"""

leg = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000"
)

# Compute checksum
checksum = leg.compute_checksum()
print(f"Checksum: {checksum}")
# Output: Checksum: 3fb163de795f25067a46c44a47c6b0ba39c7a5fa8f6ba19a5a8c41c8a7f3f2b4

# Store both leg data and checksum
import json
data_with_checksum = {
    "leg": leg.to_dict(),
    "checksum": checksum,
    "timestamp": datetime.now().isoformat()
}

with open('leg_with_integrity.json', 'w') as f:
    json.dump(data_with_checksum, f)


# Verify on load
with open('leg_with_integrity.json', 'r') as f:
    loaded = json.load(f)
    leg_dict = loaded['leg']
    stored_checksum = loaded['checksum']
    
    is_valid = TradeLegV1.verify_checksum(leg_dict, stored_checksum)
    
    if is_valid:
        print("✓ Data integrity verified - no corruption detected")
        leg = TradeLegV1.from_dict(leg_dict)
    else:
        print("✗ CORRUPTION DETECTED - Data has been tampered with!")
        # Take action: log error, alert admin, skip this leg, etc.


# Example: Detecting corruption
corrupted_dict = leg_dict.copy()
corrupted_dict['entry_price'] = 51.0  # Tamper with the data
is_valid = TradeLegV1.verify_checksum(corrupted_dict, stored_checksum)
print(f"Corrupted data detected: {not is_valid}")  # True - corruption detected!


# =============================================================================
# 7. ROUNDTRIP (to_dict → from_dict)
# =============================================================================

"""
Full cycle: Create → Serialize → Save → Load → Deserialize
Ensures data integrity from creation to loading.
"""

# Step 1: Create leg
original_leg = TradeLegV1(
    token="12345",
    entry_price=50.0,
    quantity=1,
    side="SELL",
    timestamp="2025-02-15T09:30:00.000000"
)

# Step 2: Serialize + compute checksum
leg_dict = original_leg.to_dict()
checksum = original_leg.compute_checksum()

# Step 3: Save to storage
storage = {
    "legs": [leg_dict],
    "checksums": {"leg_0": checksum}
}

# Step 4: Load from storage (simulated)
loaded_dict = storage["legs"][0]
loaded_checksum = storage["checksums"]["leg_0"]

# Step 5: Verify integrity
if not TradeLegV1.verify_checksum(loaded_dict, loaded_checksum):
    raise RuntimeError("Leg data corrupted!")

# Step 6: Deserialize
restored_leg = TradeLegV1.from_dict(loaded_dict)

# Step 7: Verify all fields match
assert original_leg.token == restored_leg.token
assert original_leg.entry_price == restored_leg.entry_price
assert original_leg.quantity == restored_leg.quantity
assert original_leg.side == restored_leg.side
print("✓ Roundtrip successful - data integrity verified")


# =============================================================================
# 8. INTEGRATION WITH CSV LOADING
# =============================================================================

"""
Example: Loading trade legs from CSV with error handling
"""

def load_legs_from_csv(csv_file):
    """
    Load TradeLegV1 objects from CSV with proper error handling.
    
    Args:
        csv_file: Path to CSV file (e.g., 'paper_trades.csv')
    
    Returns:
        List of TradeLegV1 objects (skips corrupted rows)
    
    Example:
        legs = load_legs_from_csv('paper_trades.csv')
        for leg in legs:
            print(f"Loaded: {leg}")
    """
    import csv
    import logging
    
    logger = logging.getLogger(__name__)
    legs = []
    
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (after header)
                try:
                    leg = TradeLegV1.from_dict(row)
                    legs.append(leg)
                    logger.info(f"Row {row_num}: {leg}")
                except (KeyError, ValueError, TypeError) as e:
                    logger.error(f"Row {row_num}: Failed to load - {e}")
                    continue  # Skip corrupted rows, continue with next
        
        logger.info(f"Loaded {len(legs)} valid legs, {row_num - 2 - len(legs)} corrupted rows skipped")
        return legs
    
    except FileNotFoundError:
        logger.error(f"File not found: {csv_file}")
        return []


# =============================================================================
# 9. MIGRATION ROADMAP (Future Versions)
# =============================================================================

"""
When we need to add new fields or change TradeLegV1, we follow this pattern:

=== EXAMPLE: Migrating from V1 to V2 ===

Step 1: Define TradeLegV2 with new fields
  @dataclass
  class TradeLegV2:
    # All V1 fields
    token: str
    entry_price: float
    quantity: int
    side: str
    timestamp: str
    version: int = 2  # <-- NEW VERSION
    
    # NEW FIELDS in V2
    strike_price: int = 0        # New field
    option_type: str = ""        # New field
    # ... etc

Step 2: Implement migration function
  def migrate_v1_to_v2(leg_v1: TradeLegV1) -> TradeLegV2:
    return TradeLegV2(
      token=leg_v1.token,
      entry_price=leg_v1.entry_price,
      quantity=leg_v1.quantity,
      side=leg_v1.side,
      timestamp=leg_v1.timestamp,
      strike_price=0,  # Default for old data
      option_type='CE',  # Default for old data
    )

Step 3: Update from_dict() to handle both versions
  @classmethod
  def from_dict(cls, data: dict):
    version = data.get("version", 1)
    
    if version == 1:
      # Load old format
      old_leg = TradeLegV1.from_dict(data)
      # Migrate to V2
      return migrate_v1_to_v2(old_leg)
    elif version == 2:
      # Load new format directly
      return cls(...)
    else:
      raise ValueError(f"Unsupported version: {version}")

Step 4: Set TradeLeg = TradeLegV2
  # So new code uses TradeLegV2 by default
  TradeLeg = TradeLegV2

Step 5: Test roundtrip with old data
  # Verify old V1 data loads correctly and migrates to V2
  old_v1_data = {'token': '12345', 'entry_price': 50, ..., 'version': 1}
  leg = TradeLegV2.from_dict(old_v1_data)
  assert leg.version == 2  # Upgraded!
  assert leg.strike_price == 0  # Default applied

This ensures:
  ✓ Old CSV/JSON files still load correctly
  ✓ No manual data migration needed
  ✓ Version detection is automatic
  ✓ Clear error messages for unsupported versions
"""


# =============================================================================
# 10. VALIDATION SUMMARY
# =============================================================================

"""
TradeLegV1 validates:

FIELD LEVEL:
  ✓ entry_price: float, > 0
  ✓ quantity: int, > 0
  ✓ side: string, must be "SELL" or "BUY"
  ✓ token: non-empty string
  ✓ timestamp: non-empty string
  ✓ version: must equal 1
  ✓ exit_price: if provided, must be > 0
  ✓ status: must be one of ["OPEN", "CLOSED", "EXITED"]

DESERIALIZATION LEVEL (from_dict):
  ✓ Version compatibility (rejects future versions)
  ✓ Required fields present
  ✓ Type conversions (string → float, etc.)
  ✓ Value constraints

DATA INTEGRITY LEVEL:
  ✓ SHA256 checksum for corruption detection
  ✓ Roundtrip guarantee (to_dict → from_dict)
  ✓ Clear error messages if data corrupted
"""

# =============================================================================
# 11. BEST PRACTICES
# =============================================================================

"""
1. Always use from_dict() when loading from external sources (CSV, JSON, DB)
   ✓ from_dict() validates everything
   ✗ Don't construct dicts manually and assume they're valid

2. Store checksums alongside data when possible
   ✓ Detect silent data corruption early
   ✗ Don't rely on absence of errors

3. Handle exceptions from from_dict() explicitly
   ✓ Log detailed error messages
   ✓ Skip corrupted rows, continue processing
   ✗ Don't let exceptions crash the system silently

4. Use version field for tracking
   ✓ Helps with future migrations
   ✓ Enables automatic version detection
   ✗ Don't hardcode version checks everywhere

5. Never modify leg.to_dict() results manually
   ✓ Use leg.exit_price = 48.5 to update leg
   ✓ Then leg.to_dict() returns updated values
   ✗ Don't mutate dicts and pass to from_dict()

Example of good practice:
  user_input = {'entry_price': '50.5', 'quantity': '1', ...}  # Could be strings!
  try:
    leg = TradeLegV1.from_dict(user_input)  # Handles type coercion & validation
  except (KeyError, ValueError) as e:
    logger.error(f"Invalid input: {e}")
    continue
  
  # Now safe to use leg
  checksum = leg.compute_checksum()
  storage = leg.to_dict()
  storage['checksum'] = checksum
  save_to_db(storage)
"""

print(__doc__)
