#!/usr/bin/env python3
"""
TradeLegManager: Safe, versioned management of trade legs.

Provides:
  - Storage of TradeLegV1 instances (type-safe)
  - Automatic migration from legacy dict format
  - Checksum computation and verification
  - Clean API: get_leg(), set_leg(), to_dict(), from_dict()
  - Graceful degradation on corrupted data
"""

import logging
import json
from typing import Dict, Optional, Any, List
from datetime import datetime
from contract import TradeLegV1

logger = logging.getLogger(__name__)


class TradeLegManager:
    """
    Manages a set of TradeLegV1 instances keyed by leg name.
    
    Example:
        manager = TradeLegManager()
        
        # Create and store a leg
        leg = TradeLegV1(token="12345", entry_price=50.0, ...)
        manager.set_leg("sell_ce", leg)
        
        # Retrieve leg
        leg = manager.get_leg("sell_ce")
        print(leg.entry_price)
        
        # Serialize/deserialize
        data = manager.to_dict()  # For storage
        manager = TradeLegManager.from_dict(data)  # For loading
    """
    
    # Valid leg names in the system
    VALID_LEG_NAMES = {"sell_ce", "sell_pe", "buy_ce", "buy_pe"}
    
    def __init__(self):
        """Initialize empty leg storage with checksums."""
        self.legs: Dict[str, TradeLegV1] = {}          # leg_name -> TradeLegV1
        self.checksums: Dict[str, str] = {}             # leg_name -> SHA256 hex
        self.creation_timestamp = datetime.now().isoformat()
    
    def set_leg(self, leg_name: str, leg: TradeLegV1) -> None:
        """
        Store a TradeLegV1 instance and compute its checksum.
        
        Args:
            leg_name: One of {"sell_ce", "sell_pe", "buy_ce", "buy_pe"}
            leg: TradeLegV1 instance (must be validated)
        
        Raises:
            ValueError: If leg_name invalid or leg not TradeLegV1
        """
        if leg_name not in self.VALID_LEG_NAMES:
            raise ValueError(
                f"Invalid leg_name '{leg_name}'. Must be one of {self.VALID_LEG_NAMES}"
            )
        
        if not isinstance(leg, TradeLegV1):
            raise TypeError(f"Expected TradeLegV1, got {type(leg)}")
        
        self.legs[leg_name] = leg
        self.checksums[leg_name] = leg.compute_checksum()
        logger.debug(f"Set leg {leg_name}: {leg}")
    
    def get_leg(self, leg_name: str) -> Optional[TradeLegV1]:
        """
        Retrieve a TradeLegV1 instance.
        
        Args:
            leg_name: Leg name (e.g., "sell_ce")
        
        Returns:
            TradeLegV1 instance or None if not set
        """
        return self.legs.get(leg_name)
    
    def has_leg(self, leg_name: str) -> bool:
        """Check if a leg exists."""
        return leg_name in self.legs
    
    def delete_leg(self, leg_name: str) -> None:
        """
        Remove a leg and its checksum.
        
        Args:
            leg_name: Leg name to delete
        """
        self.legs.pop(leg_name, None)
        self.checksums.pop(leg_name, None)
        logger.debug(f"Deleted leg {leg_name}")
    
    def get_active_legs(self) -> List[str]:
        """Get list of leg names that have been set."""
        return list(self.legs.keys())
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize all legs to dictionary (ready for JSON/storage).
        Includes checksums for integrity verification.
        
        Returns:
            {
                "version": 1,
                "creation_timestamp": "...",
                "legs": {
                    "sell_ce": {...leg_dict...},
                    "sell_pe": {...leg_dict...},
                    ...
                },
                "checksums": {
                    "sell_ce": "SHA256...",
                    "sell_pe": "SHA256...",
                    ...
                }
            }
        """
        return {
            "version": 1,
            "creation_timestamp": self.creation_timestamp,
            "legs": {
                leg_name: leg.to_dict()
                for leg_name, leg in self.legs.items()
            },
            "checksums": self.checksums.copy()
        }
    
    @classmethod
    def from_dict(cls, data: dict, skip_corrupted: bool = True) -> "TradeLegManager":
        """
        Deserialize from dictionary with integrity verification.
        
        Args:
            data: Dictionary from to_dict() or loaded from JSON
            skip_corrupted: If True, skip corrupted legs and log; if False, raise error
        
        Returns:
            TradeLegManager instance
        
        Raises:
            ValueError: If skip_corrupted=False and any leg fails validation
            KeyError: If required structure missing
        """
        if not isinstance(data, dict):
            raise TypeError(f"from_dict() expects dict, got {type(data)}")
        
        manager = cls()
        
        # Load metadata
        manager.creation_timestamp = data.get("creation_timestamp", datetime.now().isoformat())
        
        # Load checksums
        manager.checksums = data.get("checksums", {})
        
        # Load legs with verification
        legs_data = data.get("legs", {})
        skipped = []
        
        for leg_name, leg_dict in legs_data.items():
            try:
                # Verify checksum if stored
                stored_checksum = manager.checksums.get(leg_name)
                if stored_checksum:
                    if not TradeLegV1.verify_checksum(leg_dict, stored_checksum):
                        raise ValueError(
                            f"Leg '{leg_name}': Checksum mismatch - data may be corrupted"
                        )
                
                # Deserialize with validation
                leg = TradeLegV1.from_dict(leg_dict)
                manager.legs[leg_name] = leg
                logger.debug(f"Loaded leg {leg_name}: {leg}")
            
            except (KeyError, ValueError, TypeError) as e:
                skipped.append((leg_name, str(e)))
                logger.error(f"Failed to load leg '{leg_name}': {e}")
                
                if not skip_corrupted:
                    raise ValueError(
                        f"Leg '{leg_name}' failed validation: {e}"
                    )
        
        if skipped:
            logger.warning(
                f"Skipped {len(skipped)} corrupted legs: {skipped}"
            )
        
        return manager
    
    @classmethod
    def migrate_from_legacy_dict(cls, legacy_state: dict) -> "TradeLegManager":
        """
        Migrate from old dict-based leg storage to TradeLegManager.
        
        Legacy format (flat keys):
            {
                'sell_ce_token': '12345',
                'sell_ce_strike': 45000,
                'sell_ce_ref_premium': 50.0,
                'sell_ce_symbol': 'NIFTY45000CE',
                'sell_ce_qty': 1,
                'sell_ce_entered': True,
                ...and similar for sell_pe, buy_ce, buy_pe
            }
        
        New format (TradeLegV1 instances):
            Converts legacy data to TradeLegV1 with validation
        
        Args:
            legacy_state: Old state dict from before TradeLegV1
        
        Returns:
            TradeLegManager with migrated legs
        
        Example:
            old_state = {'sell_ce_token': '12345', 'sell_ce_ref_premium': 50.0, ...}
            manager = TradeLegManager.migrate_from_legacy_dict(old_state)
        """
        manager = cls()
        
        # Map legacy keys to leg names
        leg_legacy_map = {
            'sell_ce': {
                'token': 'sell_ce_token',
                'strike': 'sell_ce_strike',
                'price': 'sell_ce_ref_premium',
                'qty': 'sell_ce_qty',
                'symbol': 'sell_ce_symbol',
                'entered': 'sell_ce_entered'
            },
            'sell_pe': {
                'token': 'sell_pe_token',
                'strike': 'sell_pe_strike',
                'price': 'sell_pe_ref_premium',
                'qty': 'sell_pe_qty',
                'symbol': 'sell_pe_symbol',
                'entered': 'sell_pe_entered'
            },
            'buy_ce': {
                'token': 'buy_ce_token',
                'strike': 'buy_ce_strike',
                'price': 'buy_ce_ref_premium',
                'qty': 'buy_ce_qty',
                'symbol': 'buy_ce_symbol',
                'entered': 'buy_ce_entered'
            },
            'buy_pe': {
                'token': 'buy_pe_token',
                'strike': 'buy_pe_strike',
                'price': 'buy_pe_ref_premium',
                'qty': 'buy_pe_qty',
                'symbol': 'buy_pe_symbol',
                'entered': 'buy_pe_entered'
            }
        }
        
        for leg_name, key_map in leg_legacy_map.items():
            try:
                # Extract legacy fields
                token = legacy_state.get(key_map['token'])
                price = legacy_state.get(key_map['price'])
                qty = legacy_state.get(key_map['qty'], 1)
                entered = legacy_state.get(key_map['entered'], False)
                
                # Skip if no token (leg not used)
                if not token:
                    logger.debug(f"Skipping leg '{leg_name}' - no token in legacy state")
                    continue
                
                # Determine side from leg naming
                side = "SELL" if leg_name.startswith("sell") else "BUY"
                
                # Map legacy entered flag to status
                # Note: entered in legacy just means"selected for trade", not "closed"
                # So all migrated legs start as "OPEN" (active)
                status = "OPEN"
                
                # Create TradeLegV1 with legacy data
                leg = TradeLegV1(
                    token=str(token),
                    entry_price=float(price) if price else 0.0,
                    quantity=int(qty) if qty else 1,
                    side=side,
                    timestamp=datetime.now().isoformat(),
                    version=1,
                    leg_id=f"legacy_{leg_name}",
                    status=status  # OPEN for all migrated legs
                )
                
                manager.set_leg(leg_name, leg)
                logger.info(f"Migrated leg '{leg_name}': {leg} (legacy entered={entered})")
            
            except Exception as e:
                logger.error(f"Failed to migrate leg '{leg_name}': {e}")
                continue
        
        return manager
    
    def verify_all_checksums(self) -> bool:
        """
        Verify integrity of all legs.
        
        Returns:
            True if all legs verified, False if any checksum mismatch
        """
        all_valid = True
        
        for leg_name, leg in self.legs.items():
            stored_checksum = self.checksums.get(leg_name)
            computed_checksum = leg.compute_checksum()
            
            if stored_checksum != computed_checksum:
                logger.error(
                    f"Leg '{leg_name}': Checksum mismatch!"
                    f" Stored={stored_checksum[:16]}..., Computed={computed_checksum[:16]}..."
                )
                all_valid = False
            else:
                logger.debug(f"Leg '{leg_name}': Checksum verified ✓")
        
        return all_valid
    
    def to_csv_dict(self, leg_name: str) -> Optional[Dict[str, Any]]:
        """
        Convert a single leg to CSV-friendly dict format.
        Useful for exporting to CSV files (paper_trades.csv, etc).
        
        Args:
            leg_name: Leg name (e.g., "sell_ce")
        
        Returns:
            Dict ready for csv.DictWriter or None if leg doesn't exist
        
        Example:
            manager = TradeLegManager()
            leg = TradeLegV1(token="12345", ...)
            manager.set_leg("sell_ce", leg)
            
            csv_row = manager.to_csv_dict("sell_ce")
            # {
            #   "token": "12345",
            #   "entry_price": 50.0,
            #   "quantity": 1,
            #   "side": "SELL",
            #   ...
            # }
        """
        leg = self.get_leg(leg_name)
        if not leg:
            return None
        
        return leg.to_dict()
    
    def __repr__(self) -> str:
        """String representation for logging."""
        legs_info = ", ".join([
            f"{name}({leg.side} {leg.quantity} @ {leg.entry_price})"
            for name, leg in self.legs.items()
        ])
        return f"TradeLegManager({legs_info})"
    
    def summary(self) -> str:
        """Human-readable summary of all legs."""
        lines = ["TradeLegManager Summary:"]
        if not self.legs:
            lines.append("  (no legs)")
            return "\n".join(lines)
        
        for leg_name in sorted(self.VALID_LEG_NAMES):
            leg = self.legs.get(leg_name)
            if leg:
                lines.append(
                    f"  {leg_name:8} {leg.side:4} {leg.quantity:2} @ {leg.entry_price:8.2f} "
                    f"({leg.status:6}) created={leg.timestamp[:10]}"
                )
        
        return "\n".join(lines)
