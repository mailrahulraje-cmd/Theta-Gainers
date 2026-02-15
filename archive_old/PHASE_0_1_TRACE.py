#!/usr/bin/env python3
"""
PHASE 0/1 DEADLOCK DIAGNOSTIC TRACE SCRIPT

Instruments StrategyEngine to log all phase and leg state transitions
with timestamps, identifying blocking points and dependencies.

Usage:
    python PHASE_0_1_TRACE.py
    
    Sets environment variable to enable PHASE1_TRACE logging,
    then runs main.py with full diagnostic output.
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# Enable phase tracing
os.environ['ENABLE_PHASE1_TRACE'] = 'true'
os.environ['DEBUG_MODE'] = 'true'

# Add workspace to path
WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

from utils.logger import logger
from config import Config

class Phase01Tracer:
    """Diagnostic tracer for Phase 0/1 transitions"""
    
    def __init__(self):
        self.trace_log = []
        self.start_time = time.time()
        self.last_state_dump = {}
        
    def log_phase_event(self, event_type, details):
        """Log a phase event with timestamp"""
        elapsed = time.time() - self.start_time
        entry = {
            'time_elapsed': f'{elapsed:.2f}s',
            'timestamp': datetime.now().isoformat(),
            'event': event_type,
            'details': details
        }
        self.trace_log.append(entry)
        
        # Also log to main logger
        logger.info(f"[PHASE_TRACE] ({elapsed:.2f}s) {event_type}: {details}")
    
    def log_state_snapshot(self, state_dict, phase=None):
        """Log current state as readable summary"""
        if not state_dict:
            return
        
        elapsed = time.time() - self.start_time
        
        # Extract key flags
        snapshot = {
            'elapsed': f'{elapsed:.2f}s',
            'phase': phase or state_dict.get('phase', 'UNKNOWN'),
            'phase0_done': state_dict.get('phase0_done', False),
            'phase1_done': state_dict.get('phase1_done', False),
            'phase1_attempts': state_dict.get('_phase1_attempt_count', 0),
            'phase1_without_hedges': state_dict.get('_phase1_completed_without_hedges', False),
            'sell_ce_leg_ready': state_dict.get('sell_ce_leg_ready', False),
            'sell_pe_leg_ready': state_dict.get('sell_pe_leg_ready', False),
            'buy_ce_leg_ready': state_dict.get('buy_ce_leg_ready', False),
            'buy_pe_leg_ready': state_dict.get('buy_pe_leg_ready', False),
            'sell_ce_entered': state_dict.get('sell_ce_entered', False),
            'sell_pe_entered': state_dict.get('sell_pe_entered', False),
            'buy_ce_entered': state_dict.get('buy_ce_entered', False),
            'buy_pe_entered': state_dict.get('buy_pe_entered', False),
        }
        
        # Only log if changed
        if snapshot != self.last_state_dump:
            logger.info("=" * 100)
            logger.info(f"[STATE_SNAPSHOT] {elapsed:.2f}s")
            logger.info(f"  Phase: {snapshot['phase']}")
            logger.info(f"  Phase 0: done={snapshot['phase0_done']}")
            logger.info(f"  Phase 1: done={snapshot['phase1_done']} attempts={snapshot['phase1_attempts']} without_hedges={snapshot['phase1_without_hedges']}")
            logger.info(f"  SELL CE: ready={snapshot['sell_ce_leg_ready']} entered={snapshot['sell_ce_entered']}")
            logger.info(f"  SELL PE: ready={snapshot['sell_pe_leg_ready']} entered={snapshot['sell_pe_entered']}")
            logger.info(f"  BUY CE:  ready={snapshot['buy_ce_leg_ready']} entered={snapshot['buy_ce_entered']}")
            logger.info(f"  BUY PE:  ready={snapshot['buy_pe_leg_ready']} entered={snapshot['buy_pe_entered']}")
            logger.info("=" * 100)
            
            self.last_state_dump = snapshot

def patch_engine_for_tracing(engine_instance, tracer):
    """Patch StrategyEngine methods to add diagnostic tracing"""
    
    # Store original methods
    original_phase_monitor = engine_instance._phase_monitor
    original_execute_phase0 = engine_instance._execute_phase0
    original_execute_phase1 = engine_instance._execute_phase1
    original_select_by_delta = engine_instance._select_by_delta
    original_check_sell_entry = engine_instance._check_sell_entry
    original_check_buy_entry = engine_instance._check_buy_entry
    original_entry_monitor = engine_instance._entry_monitor
    
    def traced_phase_monitor():
        """Traced version of _phase_monitor"""
        tracer.log_phase_event('PHASE_MONITOR_START', 'Phase monitor thread started')
        
        iteration_count = 0
        while not engine_instance._stop_event.is_set():
            try:
                iteration_count += 1
                now = datetime.now(Config.TZ)
                ct = now.time()
                
                # Log state at each iteration
                if iteration_count % 100 == 0:  # Every 100 iterations
                    tracer.log_state_snapshot(
                        engine_instance.state.state if hasattr(engine_instance.state, 'state') else {},
                        phase=engine_instance.state.get('phase', 'UNKNOWN')
                    )
                
                # Log phase transition decisions
                if ct < Config.PHASE0_START:
                    current_phase = engine_instance.state.get('phase')
                    if current_phase != 'STANDBY':
                        tracer.log_phase_event('PHASE_TRANSITION', f'Moving to STANDBY (ct={ct.strftime("%H:%M:%S")})')
                
                elif Config.PHASE0_START <= ct < Config.PHASE0_END:
                    phase0_done = engine_instance.state.get('phase0_done', False)
                    if not phase0_done:
                        tracer.log_phase_event('EXECUTING_PHASE0', f'phase0_done={phase0_done}, executing...')
                    else:
                        tracer.log_phase_event('PHASE0_ALREADY_DONE', f'Skipping, phase0_done=True')
                
                elif Config.PHASE1_START <= ct < Config.PHASE1_END:
                    phase1_done = engine_instance.state.get('phase1_done', False)
                    attempts = engine_instance.state.get('_phase1_attempt_count', 0)
                    if not phase1_done:
                        tracer.log_phase_event(
                            'EXECUTING_PHASE1',
                            f'phase1_done={phase1_done}, attempt {attempts + 1}, executing...'
                        )
                    else:
                        tracer.log_phase_event('PHASE1_ALREADY_DONE', f'Skipping, phase1_done=True')
                
                elif ct >= Config.PHASE1_END and ct < Config.SQUAREOFF_TIME:
                    tracer.log_phase_event('TRADING_ACTIVE', f'IN_TRADE window (ct={ct.strftime("%H:%M:%S")})')
                
                elif ct >= Config.SQUAREOFF_TIME:
                    tracer.log_phase_event('MARKET_CLOSED', f'CLOSED window (ct={ct.strftime("%H:%M:%S")})')
                
                # Call original implementation
                original_phase_monitor()
                
            except Exception as e:
                tracer.log_phase_event('PHASE_MONITOR_ERROR', f'Exception: {e}')
                original_phase_monitor()
    
    def traced_execute_phase0():
        """Traced version of _execute_phase0"""
        tracer.log_phase_event('PHASE0_START', 'Starting Phase 0 execution')
        try:
            result = original_execute_phase0()
            phase0_done = engine_instance.state.get('phase0_done', False)
            tracer.log_phase_event('PHASE0_RESULT', 
                f'phase0_done={phase0_done}, SELL_CE_ready={engine_instance.state.get("sell_ce_leg_ready")}, '
                f'SELL_PE_ready={engine_instance.state.get("sell_pe_leg_ready")}')
            return result
        except Exception as e:
            tracer.log_phase_event('PHASE0_ERROR', f'Exception: {e}')
            raise
    
    def traced_execute_phase1():
        """Traced version of _execute_phase1"""
        attempt = engine_instance.state.get('_phase1_attempt_count', 0)
        max_att = Config.PHASE1_MAX_ATTEMPTS
        
        tracer.log_phase_event(
            'PHASE1_ATTEMPT_START',
            f'Attempt {attempt + 1}/{max_att}, BUY_CE_ready={engine_instance.state.get("buy_ce_leg_ready")}, '
            f'BUY_PE_ready={engine_instance.state.get("buy_pe_leg_ready")}'
        )
        
        try:
            result = original_execute_phase1()
            
            phase1_done = engine_instance.state.get('phase1_done', False)
            final_attempts = engine_instance.state.get('_phase1_attempt_count', 0)
            without_hedges = engine_instance.state.get('_phase1_completed_without_hedges', False)
            
            tracer.log_phase_event(
                'PHASE1_ATTEMPT_RESULT',
                f'Attempt {final_attempts}/{max_att} - '
                f'phase1_done={phase1_done}, '
                f'BUY_CE_ready={engine_instance.state.get("buy_ce_leg_ready")}, '
                f'BUY_PE_ready={engine_instance.state.get("buy_pe_leg_ready")}, '
                f'without_hedges={without_hedges}'
            )
            
            return result
        except Exception as e:
            tracer.log_phase_event('PHASE1_ERROR', f'Attempt {attempt + 1} - Exception: {e}')
            raise
    
    def traced_select_by_delta(min_strike, max_strike, opt_type, expiry, target_delta):
        """Traced version of _select_by_delta"""
        tracer.log_phase_event(
            'SELECT_BY_DELTA_START',
            f'Type={opt_type}, Range=[{min_strike}, {max_strike}], Target_Delta={target_delta}'
        )
        
        try:
            result = original_select_by_delta(min_strike, max_strike, opt_type, expiry, target_delta)
            
            if result:
                tracer.log_phase_event(
                    'SELECT_BY_DELTA_SUCCESS',
                    f'Type={opt_type} - Found: Strike={result.get("strike")}, Delta={result.get("delta")}, LTP={result.get("ltp")}'
                )
            else:
                tracer.log_phase_event('SELECT_BY_DELTA_FAILED', f'Type={opt_type} - No option found in range')
            
            return result
        except Exception as e:
            tracer.log_phase_event('SELECT_BY_DELTA_ERROR', f'Type={opt_type} - Exception: {e}')
            raise
    
    def traced_check_sell_entry(ot):
        """Traced version of _check_sell_entry"""
        leg_key = f'sell_{ot}'
        leg_ready = engine_instance.state.get(f'{leg_key}_leg_ready', False)
        leg_entered = engine_instance.state.get(f'{leg_key}_entered', False)
        
        if not leg_ready:
            tracer.log_phase_event('SELL_ENTRY_SKIP', f'{ot.upper()} - Leg not ready')
            return
        
        if leg_entered:
            tracer.log_phase_event('SELL_ENTRY_SKIP', f'{ot.upper()} - Already entered')
            return
        
        tracer.log_phase_event('CHECK_SELL_ENTRY', f'{ot.upper()} - Checking entry condition')
        
        try:
            result = original_check_sell_entry(ot)
            
            new_entered = engine_instance.state.get(f'{leg_key}_entered', False)
            if new_entered:
                tracer.log_phase_event('SELL_ENTRY_SUCCESS', 
                    f'{ot.upper()} - Entry executed at {engine_instance.state.get(f"sell_{ot}_entry_price", 0.0):.2f}')
            else:
                tracer.log_phase_event('SELL_ENTRY_CONDITION_NOT_MET', f'{ot.upper()} - Decay insufficient')
            
            return result
        except Exception as e:
            tracer.log_phase_event('SELL_ENTRY_ERROR', f'{ot.upper()} - Exception: {e}')
            raise
    
    def traced_check_buy_entry(ot):
        """Traced version of _check_buy_entry"""
        leg_key = f'buy_{ot}'
        leg_ready = engine_instance.state.get(f'{leg_key}_leg_ready', False)
        leg_entered = engine_instance.state.get(f'{leg_key}_entered', False)
        
        if not leg_ready:
            tracer.log_phase_event('BUY_ENTRY_SKIP', f'{ot.upper()} - Leg not ready')
            return
        
        if leg_entered:
            tracer.log_phase_event('BUY_ENTRY_SKIP', f'{ot.upper()} - Already entered')
            return
        
        tracer.log_phase_event('CHECK_BUY_ENTRY', f'{ot.upper()} - Checking entry condition')
        
        try:
            result = original_check_buy_entry(ot)
            
            new_entered = engine_instance.state.get(f'{leg_key}_entered', False)
            if new_entered:
                tracer.log_phase_event('BUY_ENTRY_SUCCESS',
                    f'{ot.upper()} - Entry executed at {engine_instance.state.get(f"buy_{ot}_entry_price", 0.0):.2f}')
            else:
                tracer.log_phase_event('BUY_ENTRY_CONDITION_NOT_MET', f'{ot.upper()} - Decay insufficient')
            
            return result
        except Exception as e:
            tracer.log_phase_event('BUY_ENTRY_ERROR', f'{ot.upper()} - Exception: {e}')
            raise
    
    def traced_entry_monitor():
        """Traced version of _entry_monitor"""
        tracer.log_phase_event('ENTRY_MONITOR_START', 'Entry monitor thread started')
        iteration_count = 0
        
        while not engine_instance._stop_event.is_set():
            try:
                iteration_count += 1
                
                # Log state periodically
                if iteration_count % 50 == 0:  # Every 50 iterations
                    tracer.log_state_snapshot(
                        engine_instance.state.state if hasattr(engine_instance.state, 'state') else {},
                        phase=engine_instance.state.get('phase', 'UNKNOWN')
                    )
                
                # Call original implementation
                original_entry_monitor()
                
            except Exception:
                original_entry_monitor()
    
    # Apply patches
    engine_instance._phase_monitor = traced_phase_monitor
    engine_instance._execute_phase0 = traced_execute_phase0
    engine_instance._execute_phase1 = traced_execute_phase1
    engine_instance._select_by_delta = traced_select_by_delta
    engine_instance._check_sell_entry = traced_check_sell_entry
    engine_instance._check_buy_entry = traced_check_buy_entry
    engine_instance._entry_monitor = traced_entry_monitor
    
    return tracer

def main():
    """Run the trading system with Phase 0/1 diagnostic tracing"""
    
    logger.info("=" * 100)
    logger.info("PHASE 0/1 DEADLOCK DIAGNOSTIC TRACE")
    logger.info("=" * 100)
    logger.info("This script instruments the StrategyEngine to trace all Phase 0/1 transitions")
    logger.info("and identify blocking points.")
    logger.info("")
    
    # Import main module
    try:
        from main import main as trading_main
        
        # The main function will create the engine
        # We'll need to patch it after creation
        # For now, just run main and let the patching happen at engine creation time
        trading_main()
        
    except KeyboardInterrupt:
        logger.info("Diagnostic trace interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Diagnostic trace failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
