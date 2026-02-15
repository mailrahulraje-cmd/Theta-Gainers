#!/usr/bin/env python3
"""
CSV/JSON Export and Import utilities for TradeLegV1

Handles:
- Exporting legs to CSV (paper_trades.csv format)
- Exporting legs to JSON with checksums
- Reloading from CSV/JSON with integrity verification
- Versioning and migration support
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from contract import TradeLegV1
from core.trade_leg_manager import TradeLegManager

logger = logging.getLogger(__name__)


class TradeLegCSVExporter:
    """
    Exports TradeLegV1 instances to CSV format.
    
    Format compatible with existing paper_trades.csv:
        timestamp, leg_name, token, side, quantity, entry_price, status, exit_price, pnl, checksum
    """
    
    FIELDNAMES = [
        'timestamp',
        'leg_name',
        'token',
        'side',
        'quantity',
        'entry_price',
        'status',
        'exit_price',
        'pnl',
        'leg_id',
        'version',
        'checksum'
    ]
    
    @staticmethod
    def export_legs_to_csv(
        leg_manager: TradeLegManager,
        csv_file: str,
        append_mode: bool = True
    ) -> bool:
        """
        Export all legs from TradeLegManager to CSV file.
        
        Args:
            leg_manager: TradeLegManager instance with legs
            csv_file: Path to CSV file
            append_mode: If True, append to existing file; if False, overwrite
        
        Returns:
            True if successful, False otherwise
        
        Example:
            if TradeLegCSVExporter.export_legs_to_csv(manager, "trades.csv"):
                logger.info("Exported to CSV")
        """
        try:
            # Create directory if needed
            Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
            
            mode = 'a' if append_mode and os.path.exists(csv_file) else 'w'
            
            with open(csv_file, mode, newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=TradeLegCSVExporter.FIELDNAMES)
                
                # Write header if new file
                if mode == 'w':
                    writer.writeheader()
                
                # Write each leg
                for leg_name in leg_manager.get_active_legs():
                    leg = leg_manager.get_leg(leg_name)
                    if leg:
                        row = TradeLegCSVExporter._leg_to_csv_row(
                            leg_name,
                            leg,
                            leg_manager.checksums.get(leg_name, "")
                        )
                        writer.writerow(row)
                        logger.debug(f"Exported leg '{leg_name}' to CSV")
            
            logger.info(f"Exported {len(leg_manager.get_active_legs())} legs to {csv_file}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to export legs to CSV: {e}")
            return False
    
    @staticmethod
    def _leg_to_csv_row(
        leg_name: str,
        leg: TradeLegV1,
        checksum: str
    ) -> Dict[str, Any]:
        """Convert TradeLegV1 to CSV row dict."""
        return {
            'timestamp': leg.timestamp,
            'leg_name': leg_name,
            'token': leg.token,
            'side': leg.side,
            'quantity': leg.quantity,
            'entry_price': leg.entry_price,
            'status': leg.status,
            'exit_price': leg.exit_price or '',
            'pnl': leg.pnl or '',
            'leg_id': leg.leg_id,
            'version': leg.version,
            'checksum': checksum
        }
    
    @staticmethod
    def import_legs_from_csv(
        csv_file: str,
        skip_corrupted: bool = True
    ) -> Optional[TradeLegManager]:
        """
        Import legs from CSV file.
        
        Args:
            csv_file: Path to CSV file
            skip_corrupted: If True, skip rows with integrity issues; if False, raise error
        
        Returns:
            TradeLegManager with loaded legs, or None if error
        
        Example:
            manager = TradeLegCSVExporter.import_legs_from_csv("trades.csv")
            if manager:
                for leg_name in manager.get_active_legs():
                    leg = manager.get_leg(leg_name)
                    print(leg)
        """
        try:
            if not os.path.exists(csv_file):
                logger.error(f"CSV file not found: {csv_file}")
                return None
            
            manager = TradeLegManager()
            skipped = []
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (after header)
                    try:
                        leg_name = row.get('leg_name', '')
                        if not leg_name:
                            logger.warning(f"Row {row_num}: Missing leg_name")
                            continue
                        
                        # Verify checksum if present
                        stored_checksum = row.get('checksum', '')
                        
                        # Create TradeLegV1 from row
                        leg = TradeLegV1.from_dict({
                            'token': row['token'],
                            'entry_price': float(row['entry_price']),
                            'quantity': int(row['quantity']),
                            'side': row['side'],
                            'timestamp': row['timestamp'],
                            'version': int(row.get('version', 1)),
                            'leg_id': row.get('leg_id', ''),
                            'status': row.get('status', 'OPEN'),
                            'exit_price': float(row['exit_price']) if row.get('exit_price') else None,
                            'pnl': float(row['pnl']) if row.get('pnl') else None,
                        })
                        
                        # Verify checksum
                        if stored_checksum:
                            if not TradeLegV1.verify_checksum(leg.to_dict(), stored_checksum):
                                raise ValueError(
                                    f"Checksum mismatch at row {row_num}: "
                                    f"data may be corrupted"
                                )
                        
                        manager.set_leg(leg_name, leg)
                        logger.debug(f"Row {row_num}: Loaded leg '{leg_name}'")
                    
                    except Exception as e:
                        skipped.append((row_num, leg_name, str(e)))
                        logger.error(f"Row {row_num}: Failed to load - {e}")
                        
                        if not skip_corrupted:
                            raise ValueError(
                                f"Row {row_num}: {e}"
                            )
            
            if skipped:
                logger.warning(
                    f"Skipped {len(skipped)} rows due to errors: {skipped}"
                )
            
            logger.info(
                f"Imported {len(manager.get_active_legs())} legs from {csv_file}"
            )
            return manager
        
        except Exception as e:
            logger.error(f"Failed to import legs from CSV: {e}")
            return None


class TradeLegJSONExporter:
    """
    Exports TradeLegV1 instances to JSON format with full metadata.
    
    Includes:
    - All leg fields
    - Checksums for integrity verification
    - Version info for future migrations
    - Export timestamp and metadata
    """
    
    @staticmethod
    def export_legs_to_json(
        leg_manager: TradeLegManager,
        json_file: str,
        include_metadata: bool = True
    ) -> bool:
        """
        Export legs to JSON file with checksums.
        
        Args:
            leg_manager: TradeLegManager instance
            json_file: Path to JSON file
            include_metadata: Include export timestamp and metadata
        
        Returns:
            True if successful, False otherwise
        
        Example:
            if TradeLegJSONExporter.export_legs_to_json(manager, "legs.json"):
                logger.info("Exported to JSON")
        """
        try:
            # Create directory if needed
            Path(json_file).parent.mkdir(parents=True, exist_ok=True)
            
            # Get manager state
            data = leg_manager.to_dict()
            
            # Add metadata
            if include_metadata:
                data['export_timestamp'] = datetime.now().isoformat()
                data['export_count'] = len(leg_manager.get_active_legs())
                data['leg_names'] = leg_manager.get_active_legs()
            
            # Write to temporary file first (atomic write)
            tmp_file = f"{json_file}.tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            # Atomic rename
            if os.path.exists(json_file):
                os.replace(json_file, f"{json_file}.backup")
            os.replace(tmp_file, json_file)
            
            logger.info(f"Exported {data.get('export_count', 0)} legs to {json_file}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to export legs to JSON: {e}")
            return False
    
    @staticmethod
    def import_legs_from_json(
        json_file: str,
        skip_corrupted: bool = True
    ) -> Optional[TradeLegManager]:
        """
        Import legs from JSON file with integrity verification.
        
        Args:
            json_file: Path to JSON file
            skip_corrupted: If True, skip corrupted legs; if False, raise error
        
        Returns:
            TradeLegManager with loaded legs, or None if error
        
        Example:
            manager = TradeLegJSONExporter.import_legs_from_json("legs.json")
            if manager:
                print(f"Loaded {len(manager.get_active_legs())} legs")
        """
        try:
            if not os.path.exists(json_file):
                logger.error(f"JSON file not found: {json_file}")
                return None
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load manager with verification
            manager = TradeLegManager.from_dict(data, skip_corrupted=skip_corrupted)
            
            logger.info(
                f"Imported {len(manager.get_active_legs())} legs from {json_file}"
            )
            return manager
        
        except Exception as e:
            logger.error(f"Failed to import legs from JSON: {e}")
            return None


class TradeLogExporter:
    """
    Exports trade leg history with PnL tracking.
    
    Creates detailed trade logs showing:
    - Entry/exit prices
    - Quantities
    - PnL per leg
    - Timestamps
    """
    
    @staticmethod
    def export_trade_log(
        closed_legs: List[TradeLegV1],
        log_file: str
    ) -> bool:
        """
        Export closed legs to trade log.
        
        Args:
            closed_legs: List of closed TradeLegV1 instances
            log_file: Path to log file
        
        Returns:
            True if successful
        """
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            
            fieldnames = [
                'timestamp',
                'token',
                'side',
                'quantity',
                'entry_price',
                'exit_price',
                'pnl',
                'duration'
            ]
            
            with open(log_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                # Write header if new file
                if f.tell() == 0:
                    writer.writeheader()
                
                # Write each closed leg
                for leg in closed_legs:
                    if leg.status == "CLOSED" and leg.exit_price:
                        row = {
                            'timestamp': leg.timestamp,
                            'token': leg.token,
                            'side': leg.side,
                            'quantity': leg.quantity,
                            'entry_price': leg.entry_price,
                            'exit_price': leg.exit_price,
                            'pnl': leg.pnl or 0.0,
                            'duration': 'N/A'  # Would need entry/exit time for this
                        }
                        writer.writerow(row)
            
            logger.info(f"Exported {len(closed_legs)} closed legs to {log_file}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to export trade log: {e}")
            return False
