#!/usr/bin/env python3
"""
State Schema Validation and Versioning

Implements:
- Schema validation for state structure
- Version tracking and automatic migration
- Checksum-based integrity verification
- Helper functions for type-safe state access
"""

import json
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Current state schema version
STATE_VERSION = "2.0"

# Required fields in state
REQUIRED_STATE_FIELDS = [
    "_version",
    "_checksum",
    "phase",
    "trade_state",
    "legs"
]

# Leg names that must exist
REQUIRED_LEGS = {"sell_ce", "sell_pe", "buy_ce", "buy_pe"}


def validate_state_schema(state: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate state structure is complete and well-formed.
    
    Args:
        state: The state dictionary to validate
    
    Returns:
        (valid, message) - True if valid, False + error message otherwise
    
    Raises:
        ValueError: If validation fails and strict mode enabled
    """
    if not isinstance(state, dict):
        return False, f"State must be dict, got {type(state)}"
    
    if not state:
        return False, "State is empty - cannot validate"
    
    # Check required fields
    missing_fields = [f for f in REQUIRED_STATE_FIELDS if f not in state]
    if missing_fields:
        return False, f"Missing required fields: {missing_fields}"
    
    # Validate field types
    if not isinstance(state.get("_version"), str):
        return False, "_version must be string"
    
    if not isinstance(state.get("_checksum"), str):
        return False, "_checksum must be string"
    
    if not isinstance(state.get("phase"), str):
        return False, "phase must be string"
    
    if not isinstance(state.get("trade_state"), dict):
        return False, "trade_state must be dict"
    
    if not isinstance(state.get("legs"), dict):
        return False, "legs must be dict"
    
    # Validate leg structure
    legs = state.get("legs", {})
    if not legs:
        return False, "legs dict cannot be empty"
    
    for leg_name in REQUIRED_LEGS:
        if leg_name not in legs:
            return False, f"Missing leg: {leg_name}"
        
        leg_data = legs[leg_name]
        if not isinstance(leg_data, dict):
            return False, f"Leg {leg_name} must be dict, got {type(leg_data)}"
    
    # Validate trade_state has all 4 legs
    trade_state = state.get("trade_state", {})
    missing_trade_states = [l for l in REQUIRED_LEGS if l not in trade_state]
    if missing_trade_states:
        return False, f"trade_state missing legs: {missing_trade_states}"
    
    return True, "State structure valid"


def compute_state_checksum(state: Dict[str, Any], exclude_fields: list = None) -> str:
    """
    Compute SHA256 checksum of state data for integrity verification.
    
    Args:
        state: The state dictionary
        exclude_fields: Fields to exclude from checksum (e.g., ["_checksum"])
    
    Returns:
        Hex string of SHA256 hash
    """
    if exclude_fields is None:
        exclude_fields = ["_checksum"]
    
    # Create copy excluding checksum field
    data_to_hash = {k: v for k, v in state.items() if k not in exclude_fields}
    
    # Serialize to JSON with sorted keys for consistency
    json_str = json.dumps(data_to_hash, sort_keys=True, default=str)
    
    return hashlib.sha256(json_str.encode()).hexdigest()


def verify_state_checksum(state: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Verify state integrity using stored checksum.
    
    Args:
        state: State dict with _checksum field
    
    Returns:
        (valid, message) - True if checksum matches, False + message otherwise
    """
    if "_checksum" not in state:
        return False, "State missing _checksum field"
    
    stored_checksum = state["_checksum"]
    computed_checksum = compute_state_checksum(state)
    
    if stored_checksum != computed_checksum:
        return False, (
            f"Checksum mismatch! Stored={stored_checksum[:16]}... "
            f"Computed={computed_checksum[:16]}..."
        )
    
    return True, "Checksum verified"


def ensure_state_valid(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure state has all required fields with version and checksum.
    Adds missing fields if needed.
    
    Args:
        state: State dict (may be incomplete)
    
    Returns:
        Enhanced state with _version and _checksum
    """
    # Add version if missing
    if "_version" not in state:
        state["_version"] = STATE_VERSION
        logger.info(f"Added _version={STATE_VERSION} to state")
    
    # Ensure basic structure
    if "phase" not in state:
        state["phase"] = "INIT"
    
    if "trade_state" not in state:
        state["trade_state"] = {leg: "IDLE" for leg in REQUIRED_LEGS}
    
    if "legs" not in state:
        state["legs"] = {}
    
    # Compute and set checksum
    state["_checksum"] = compute_state_checksum(state)
    
    return state


def migrate_state_v1_to_v2(old_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate state from v1.0 (flat keys) to v2.0 (structured).
    
    Legacy v1.0 format:
    {
        'sell_ce_token': '12345',
        'sell_ce_entered': True,
        'sell_ce_entry_price': 50.0,
        ...
    }
    
    New v2.0 format:
    {
        '_version': '2.0',
        '_checksum': '...',
        'phase': 'INIT',
        'trade_state': {'sell_ce': 'ENTERED', ...},
        'legs': {'sell_ce': {...}, ...}
    }
    
    Args:
        old_state: State from v1.0 format
    
    Returns:
        Migrated state in v2.0 format
    """
    logger.info("Migrating state from v1.0 to v2.0 format")
    
    new_state = {
        "_version": STATE_VERSION,
        "phase": old_state.get("phase", "INIT"),
        "trade_state": old_state.get("trade_state", {}),
        "legs": {}
    }
    
    # Migrate each leg
    for leg_name in REQUIRED_LEGS:
        leg_key = f"{leg_name}_"
        
        # Extract legacy data
        leg_data = {}
        for key, value in old_state.items():
            if key.startswith(leg_key) and not key.endswith(("_token", "_entered", "_ready")):
                # Keep other data
                pass
        
        # Check if leg was entered
        entered_key = f"{leg_name}_entered"
        if old_state.get(entered_key):
            new_state["trade_state"][leg_name] = "ENTERED"
        elif old_state.get(f"{leg_name}_leg_ready"):
            new_state["trade_state"][leg_name] = "READY"
        else:
            new_state["trade_state"][leg_name] = "IDLE"
        
        # Preserve leg structure if exists in old state
        if f"{leg_name}_token" in old_state:
            new_state["legs"][leg_name] = {
                "token": old_state.get(f"{leg_name}_token"),
                "entered": old_state.get(f"{leg_name}_entered", False),
                "strike": old_state.get(f"{leg_name}_strike"),
                "qty": old_state.get(f"{leg_name}_qty"),
            }
        else:
            new_state["legs"][leg_name] = {}
    
    # Compute checksum
    new_state["_checksum"] = compute_state_checksum(new_state)
    
    logger.info("State migration v1.0 -> v2.0 complete")
    return new_state


def validate_and_migrate_state(state: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """
    Complete validation and migration pipeline.
    
    Args:
        state: State dict (any version)
    
    Returns:
        (validated_state, message) - Validated v2.0 state + message
    
    Raises:
        ValueError: If validation fails and cannot be auto-fixed
    """
    if not state:
        logger.warning("Empty state provided, creating new one")
        return ensure_state_valid({}), "Created new v2.0 state"
    
    # Check version and migrate if needed
    version = state.get("_version", "1.0")
    if version != STATE_VERSION:
        logger.info(f"State version {version} detected, migrating to {STATE_VERSION}")
        state = migrate_state_v1_to_v2(state)
    
    # Verify checksum
    checksum_valid, checksum_msg = verify_state_checksum(state)
    if not checksum_valid:
        logger.error(f"[CHECKSUM] {checksum_msg}")
        logger.warning("Continuing with corrupted data - manual review recommended")
    
    # Validate schema
    valid, schema_msg = validate_state_schema(state)
    if not valid:
        logger.warning(f"Schema validation failed: {schema_msg}")
        logger.info("Attempting to auto-fix state...")
        state = ensure_state_valid(state)
        valid, schema_msg = validate_state_schema(state)
        if not valid:
            raise ValueError(f"State validation failed: {schema_msg}")
    
    return state, "State validation complete"


def get_leg_safe(state: Dict[str, Any], leg_name: str) -> Optional[Dict[str, Any]]:
    """
    Safely retrieve leg data from state with validation.
    
    Args:
        state: State dict
        leg_name: Leg name (e.g., "sell_ce")
    
    Returns:
        Leg data dict or None if not found/invalid
    """
    if leg_name not in REQUIRED_LEGS:
        logger.warning(f"Invalid leg_name: {leg_name}")
        return None
    
    legs = state.get("legs", {})
    leg_data = legs.get(leg_name)
    
    if not leg_data:
        logger.debug(f"Leg {leg_name} not found in state")
        return None
    
    return leg_data


def get_leg_token(state: Dict[str, Any], leg_name: str) -> Optional[str]:
    """
    Safely get token for a specific leg.
    
    Args:
        state: State dict
        leg_name: Leg name
    
    Returns:
        Token string or None
    """
    leg_data = get_leg_safe(state, leg_name)
    if leg_data:
        return leg_data.get("token")
    return None


def get_leg_state(state: Dict[str, Any], leg_name: str) -> str:
    """
    Safely get state/status of a specific leg.
    
    Args:
        state: State dict
        leg_name: Leg name
    
    Returns:
        State string (IDLE, READY, ENTERED, etc.)
    """
    trade_state = state.get("trade_state", {})
    return trade_state.get(leg_name, "IDLE")


def is_leg_entered(state: Dict[str, Any], leg_name: str) -> bool:
    """
    Check if a leg is entered (has open position).
    
    Args:
        state: State dict
        leg_name: Leg name
    
    Returns:
        True if leg is ENTERED
    """
    return get_leg_state(state, leg_name) == "ENTERED"


def has_any_entered_leg(state: Dict[str, Any]) -> bool:
    """
    Check if any leg is entered.
    
    Args:
        state: State dict
    
    Returns:
        True if any leg is ENTERED
    """
    return any(is_leg_entered(state, leg) for leg in REQUIRED_LEGS)
