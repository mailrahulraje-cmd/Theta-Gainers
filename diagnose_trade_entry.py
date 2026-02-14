#!/usr/bin/env python3
"""
Trade Entry Diagnostic Script
Identifies why the system is not entering trades even when conditions are met.

This script checks:
1. Phase progression issues
2. Leg locking issues  
3. Token subscription issues
4. LTP availability issues
5. Entry condition calculation issues
6. Order placement issues
7. State management issues
"""

import json
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from datetime import datetime, time as dt_time

class TradeDiagnostic:
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.info = []
        
    def add_issue(self, category, message):
        self.issues.append(f" [{category}] {message}")
        
    def add_warning(self, category, message):
        self.warnings.append(f"  [{category}] {message}")
        
    def add_info(self, category, message):
        self.info.append(f"  [{category}] {message}")
    
    def check_configuration(self):
        """Check configuration issues"""
        print("\n" + "="*80)
        print("1. CONFIGURATION CHECK")
        print("="*80)
        
        # Check time windows
        if Config.PHASE0_START >= Config.PHASE0_END:
            self.add_issue("CONFIG", "PHASE0_START >= PHASE0_END - Phase 0 window is invalid")
        else:
            duration = (datetime.combine(datetime.today(), Config.PHASE0_END) - 
                       datetime.combine(datetime.today(), Config.PHASE0_START)).total_seconds()
            self.add_info("CONFIG", f"Phase 0 window: {duration}s ({Config.PHASE0_START} to {Config.PHASE0_END})")
            if duration < 5:
                self.add_warning("CONFIG", f"Phase 0 window very short: {duration}s - may not complete in time")
        
        if Config.PHASE1_START >= Config.PHASE1_END:
            self.add_issue("CONFIG", "PHASE1_START >= PHASE1_END - Phase 1 window is invalid")
        else:
            duration = (datetime.combine(datetime.today(), Config.PHASE1_END) - 
                       datetime.combine(datetime.today(), Config.PHASE1_START)).total_seconds()
            self.add_info("CONFIG", f"Phase 1 window: {duration}s ({Config.PHASE1_START} to {Config.PHASE1_END})")
            if duration < 15:
                self.add_warning("CONFIG", f"Phase 1 window very short: {duration}s - may not complete in time")
        
        # Check entry delay
        if Config.SELL_ENTRY_DELAY < 0:
            self.add_issue("CONFIG", f"SELL_ENTRY_DELAY is negative: {Config.SELL_ENTRY_DELAY}")
        elif Config.SELL_ENTRY_DELAY > 10:
            self.add_warning("CONFIG", f"SELL_ENTRY_DELAY very high: {Config.SELL_ENTRY_DELAY}s - trades may be delayed")
        else:
            self.add_info("CONFIG", f"SELL_ENTRY_DELAY: {Config.SELL_ENTRY_DELAY}s")
        
        # Check decay trigger
        if Config.SELL_DECAY_TRIGGER <= 0:
            self.add_issue("CONFIG", f"SELL_DECAY_TRIGGER is non-positive: {Config.SELL_DECAY_TRIGGER}")
        else:
            self.add_info("CONFIG", f"SELL_DECAY_TRIGGER: {Config.SELL_DECAY_TRIGGER}")
        
        # Check buy trigger
        if Config.BUY_TRIGGER_MULTIPLIER <= 0:
            self.add_issue("CONFIG", f"BUY_TRIGGER_MULTIPLIER is non-positive: {Config.BUY_TRIGGER_MULTIPLIER}")
        else:
            self.add_info("CONFIG", f"BUY_TRIGGER_MULTIPLIER: {Config.BUY_TRIGGER_MULTIPLIER}")
            
        if Config.BUY_TRIGGER_ABSOLUTE < 0:
            self.add_warning("CONFIG", f"BUY_TRIGGER_ABSOLUTE is negative: {Config.BUY_TRIGGER_ABSOLUTE}")
        else:
            self.add_info("CONFIG", f"BUY_TRIGGER_ABSOLUTE: {Config.BUY_TRIGGER_ABSOLUTE}")
        
        # Check modes
        self.add_info("CONFIG", f"DATA_MODE: {Config.DATA_MODE}")
        self.add_info("CONFIG", f"TRADING_MODE: {Config.TRADING_MODE}")
        
        # Check kill switches
        if Config.KILL_SWITCH_ENABLED:
            self.add_issue("CONFIG", "KILL_SWITCH_ENABLED=true - System will not trade!")
        
        if Config.NO_NEW_TRADES:
            self.add_issue("CONFIG", "NO_NEW_TRADES=true - System will not enter new trades!")
        
        if Config.EMERGENCY_EXIT_ALL:
            self.add_warning("CONFIG", "EMERGENCY_EXIT_ALL=true - System will exit all positions immediately")
        
        # Check lots
        if Config.LOTS <= 0:
            self.add_issue("CONFIG", f"LOTS is non-positive: {Config.LOTS}")
        else:
            self.add_info("CONFIG", f"LOTS: {Config.LOTS}")
    
    def check_state_file(self):
        """Check state file for issues"""
        print("\n" + "="*80)
        print("2. STATE FILE CHECK")
        print("="*80)
        
        if not Config.STATE_FILE.exists():
            self.add_warning("STATE", f"State file does not exist: {Config.STATE_FILE}")
            return
        
        try:
            with open(Config.STATE_FILE, 'r') as f:
                state = json.load(f)
        except Exception as e:
            self.add_issue("STATE", f"Cannot read state file: {e}")
            return
        
        if not state:
            self.add_info("STATE", "State file is empty (fresh start)")
            return
        
        # Check phase
        phase = state.get('phase', 'UNKNOWN')
        self.add_info("STATE", f"Current phase: {phase}")
        
        # Check phase completion
        phase0_done = state.get('phase0_done', False)
        phase1_done = state.get('phase1_done', False)
        phase1_attempts = state.get('_phase1_attempt_count', 0)
        completed_without_hedges = state.get('_phase1_completed_without_hedges', False)
        
        self.add_info("STATE", f"Phase 0 complete: {phase0_done}")
        self.add_info("STATE", f"Phase 1 complete: {phase1_done}")
        
        if phase1_attempts > 0:
            self.add_info("STATE", f"Phase 1 attempts: {phase1_attempts}/3")
        
        if completed_without_hedges:
            self.add_warning("STATE", "Phase 1 completed WITHOUT BUY hedges - SELL legs trading independently")
        
        if not phase0_done:
            self.add_warning("STATE", "Phase 0 not completed - SELL legs not locked")
            return
        
        if not phase1_done:
            if phase1_attempts >= 3:
                self.add_issue("STATE", "Phase 1 stuck - exceeded max attempts but not marked done")
                self.add_issue("STATE", "This is the INFINITE LOOP bug - needs code fix")
            else:
                self.add_warning("STATE", "Phase 1 not completed - may still be attempting")
        
        # Check leg readiness
        sell_ce_ready = state.get('sell_ce_leg_ready', False)
        sell_pe_ready = state.get('sell_pe_leg_ready', False)
        buy_ce_ready = state.get('buy_ce_leg_ready', False)
        buy_pe_ready = state.get('buy_pe_leg_ready', False)
        
        self.add_info("STATE", f"SELL CE leg ready: {sell_ce_ready}")
        self.add_info("STATE", f"SELL PE leg ready: {sell_pe_ready}")
        self.add_info("STATE", f"BUY CE leg ready: {buy_ce_ready}")
        self.add_info("STATE", f"BUY PE leg ready: {buy_pe_ready}")
        
        if not (sell_ce_ready and sell_pe_ready):
            self.add_issue("STATE", "SELL legs not ready - cannot enter trades")
        
        # Check entry status
        sell_ce_entered = state.get('sell_ce_entered', False)
        sell_pe_entered = state.get('sell_pe_entered', False)
        buy_ce_entered = state.get('buy_ce_entered', False)
        buy_pe_entered = state.get('buy_pe_entered', False)
        
        self.add_info("STATE", f"SELL CE entered: {sell_ce_entered}")
        self.add_info("STATE", f"SELL PE entered: {sell_pe_entered}")
        self.add_info("STATE", f"BUY CE entered: {buy_ce_entered}")
        self.add_info("STATE", f"BUY PE entered: {buy_pe_entered}")
        
        if sell_ce_entered and sell_pe_entered:
            self.add_warning("STATE", "SELL legs already entered - checking for exit conditions")
        
        # Check reference premiums
        sell_ce_ref = state.get('sell_ce_ref_premium')
        sell_pe_ref = state.get('sell_pe_ref_premium')
        buy_ce_ref = state.get('buy_ce_ref_premium')
        buy_pe_ref = state.get('buy_pe_ref_premium')
        
        if sell_ce_ref is not None:
            self.add_info("STATE", f"SELL CE reference premium: {sell_ce_ref:.2f}")
        else:
            self.add_warning("STATE", "SELL CE reference premium not set")
        
        if sell_pe_ref is not None:
            self.add_info("STATE", f"SELL PE reference premium: {sell_pe_ref:.2f}")
        else:
            self.add_warning("STATE", "SELL PE reference premium not set")
        
        # Check tokens
        sell_ce_token = state.get('sell_ce_token')
        sell_pe_token = state.get('sell_pe_token')
        
        if sell_ce_token:
            self.add_info("STATE", f"SELL CE token: {sell_ce_token}")
        else:
            self.add_warning("STATE", "SELL CE token not set")
        
        if sell_pe_token:
            self.add_info("STATE", f"SELL PE token: {sell_pe_token}")
        else:
            self.add_warning("STATE", "SELL PE token not set")
        
        # Check strikes
        sell_ce_strike = state.get('sell_ce_strike')
        sell_pe_strike = state.get('sell_pe_strike')
        
        if sell_ce_strike:
            self.add_info("STATE", f"SELL CE strike: {sell_ce_strike}")
        else:
            self.add_warning("STATE", "SELL CE strike not set")
        
        if sell_pe_strike:
            self.add_info("STATE", f"SELL PE strike: {sell_pe_strike}")
        else:
            self.add_warning("STATE", "SELL PE strike not set")
    
    def check_timing(self):
        """Check if current time is in trading window"""
        print("\n" + "="*80)
        print("3. TIMING CHECK")
        print("="*80)
        
        now = datetime.now(Config.TZ)
        current_time = now.time()
        
        self.add_info("TIMING", f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Check if in Phase 0 window
        if Config.PHASE0_START <= current_time < Config.PHASE0_END:
            self.add_info("TIMING", " Currently in PHASE 0 window - leg selection should be active")
        elif current_time < Config.PHASE0_START:
            secs_to_start = (datetime.combine(datetime.today(), Config.PHASE0_START) - 
                            datetime.combine(datetime.today(), current_time)).total_seconds()
            self.add_warning("TIMING", f"Before PHASE 0 start - {secs_to_start:.0f}s until Phase 0 begins")
        elif Config.PHASE0_END <= current_time < Config.PHASE1_START:
            self.add_info("TIMING", "Between Phase 0 and Phase 1 - waiting for Phase 1")
        elif Config.PHASE1_START <= current_time < Config.PHASE1_END:
            self.add_info("TIMING", " Currently in PHASE 1 window - OTM selection should be active")
        elif Config.PHASE1_END <= current_time < Config.SQUAREOFF_TIME:
            self.add_info("TIMING", " In TRADING window - entries should be active")
        elif current_time >= Config.SQUAREOFF_TIME:
            self.add_warning("TIMING", "After square-off time - no new trades")
        
        # Check entry delay window
        from datetime import timedelta
        phase1_end_dt = datetime.combine(datetime.today(), Config.PHASE1_END)
        phase1_end_plus_delay = (phase1_end_dt + timedelta(seconds=Config.SELL_ENTRY_DELAY)).time()
        
        if Config.PHASE1_END <= current_time < phase1_end_plus_delay:
            remaining = (datetime.combine(datetime.today(), phase1_end_plus_delay) - 
                        datetime.combine(datetime.today(), current_time)).total_seconds()
            self.add_info("TIMING", f"In entry delay window - {remaining:.1f}s remaining")
    
    def analyze_entry_conditions(self):
        """Analyze entry condition calculations"""
        print("\n" + "="*80)
        print("4. ENTRY CONDITION ANALYSIS")
        print("="*80)
        
        if not Config.STATE_FILE.exists():
            self.add_warning("ENTRY", "Cannot analyze - state file does not exist")
            return
        
        try:
            with open(Config.STATE_FILE, 'r') as f:
                state = json.load(f)
        except Exception as e:
            self.add_issue("ENTRY", f"Cannot read state file: {e}")
            return
        
        # Analyze SELL CE
        sell_ce_ref = state.get('sell_ce_ref_premium')
        if sell_ce_ref:
            self.add_info("ENTRY", f"\n--- SELL CE Entry Condition ---")
            self.add_info("ENTRY", f"Reference premium: {sell_ce_ref:.2f}")
            self.add_info("ENTRY", f"Required decay:  {Config.SELL_DECAY_TRIGGER:.2f}")
            self.add_info("ENTRY", f"Entry trigger: LTP  {sell_ce_ref - Config.SELL_DECAY_TRIGGER:.2f}")
            self.add_info("ENTRY", f"Formula: decay = ref - ltp; condition = (decay >= {Config.SELL_DECAY_TRIGGER})")
            
            # Show example scenarios
            for ltp in [sell_ce_ref, sell_ce_ref - 1, sell_ce_ref - 2, sell_ce_ref - 3]:
                decay = sell_ce_ref - ltp
                met = decay >= Config.SELL_DECAY_TRIGGER
                status = " ENTER" if met else " WAIT"
                self.add_info("ENTRY", f"  If LTP={ltp:.2f}: decay={decay:.2f}  {status}")
        
        # Analyze SELL PE
        sell_pe_ref = state.get('sell_pe_ref_premium')
        if sell_pe_ref:
            self.add_info("ENTRY", f"\n--- SELL PE Entry Condition ---")
            self.add_info("ENTRY", f"Reference premium: {sell_pe_ref:.2f}")
            self.add_info("ENTRY", f"Required decay:  {Config.SELL_DECAY_TRIGGER:.2f}")
            self.add_info("ENTRY", f"Entry trigger: LTP  {sell_pe_ref - Config.SELL_DECAY_TRIGGER:.2f}")
            
            for ltp in [sell_pe_ref, sell_pe_ref - 1, sell_pe_ref - 2, sell_pe_ref - 3]:
                decay = sell_pe_ref - ltp
                met = decay >= Config.SELL_DECAY_TRIGGER
                status = " ENTER" if met else " WAIT"
                self.add_info("ENTRY", f"  If LTP={ltp:.2f}: decay={decay:.2f}  {status}")
        
        # Analyze BUY CE
        buy_ce_ref = state.get('buy_ce_ref_premium')
        if buy_ce_ref:
            trigger = (buy_ce_ref * Config.BUY_TRIGGER_MULTIPLIER) + Config.BUY_TRIGGER_ABSOLUTE
            self.add_info("ENTRY", f"\n--- BUY CE Entry Condition ---")
            self.add_info("ENTRY", f"Reference premium: {buy_ce_ref:.2f}")
            self.add_info("ENTRY", f"Trigger: {trigger:.2f}")
            self.add_info("ENTRY", f"Entry condition: LTP  {trigger:.2f}")
            self.add_info("ENTRY", f"Formula: trigger = (ref * {Config.BUY_TRIGGER_MULTIPLIER}) + {Config.BUY_TRIGGER_ABSOLUTE}")
        
        # Analyze BUY PE  
        buy_pe_ref = state.get('buy_pe_ref_premium')
        if buy_pe_ref:
            trigger = (buy_pe_ref * Config.BUY_TRIGGER_MULTIPLIER) + Config.BUY_TRIGGER_ABSOLUTE
            self.add_info("ENTRY", f"\n--- BUY PE Entry Condition ---")
            self.add_info("ENTRY", f"Reference premium: {buy_pe_ref:.2f}")
            self.add_info("ENTRY", f"Trigger: {trigger:.2f}")
            self.add_info("ENTRY", f"Entry condition: LTP  {trigger:.2f}")
    
    def check_common_issues(self):
        """Check for common issues that prevent trades"""
        print("\n" + "="*80)
        print("5. COMMON ISSUES CHECK")
        print("="*80)
        
        # Issue 1: Phases not completing
        self.add_info("ISSUE", "Common Issue #1: Phases not completing in time")
        self.add_info("ISSUE", "  - Phase 0 must complete before 09:16:10 to lock SELL strikes")
        self.add_info("ISSUE", "  - Phase 1 must complete before 09:16:45 to lock BUY strikes")
        self.add_info("ISSUE", "  - If phases don't complete, legs won't be marked ready")
        
        # Issue 2: LTP not available
        self.add_info("ISSUE", "Common Issue #2: LTP not available")
        self.add_info("ISSUE", "  - WebSocket may not be connected")
        self.add_info("ISSUE", "  - Tokens may not be subscribed")
        self.add_info("ISSUE", "  - Data feed may be delayed")
        self.add_info("ISSUE", "  - Check logs for 'LTP unavailable' warnings")
        
        # Issue 3: Entry conditions never met
        self.add_info("ISSUE", "Common Issue #3: Entry conditions never met")
        self.add_info("ISSUE", "  - SELL decay trigger may be too high")
        self.add_info("ISSUE", f"  - Current: decay must be  {Config.SELL_DECAY_TRIGGER}")
        self.add_info("ISSUE", "  - If premiums don't decay enough, trade won't trigger")
        self.add_info("ISSUE", "  - Consider lowering SELL_DECAY_TRIGGER if needed")
        
        # Issue 4: Entry delay too long
        self.add_info("ISSUE", "Common Issue #4: Entry delay prevents trades")
        self.add_info("ISSUE", f"  - Current delay: {Config.SELL_ENTRY_DELAY}s after Phase 1 end")
        self.add_info("ISSUE", "  - If conditions met before delay expires, trade won't enter")
        self.add_info("ISSUE", "  - Consider reducing SELL_ENTRY_DELAY")
        
        # Issue 5: Kill switches
        if Config.KILL_SWITCH_ENABLED or Config.NO_NEW_TRADES:
            self.add_issue("ISSUE", "Kill switch is ENABLED - trades are blocked!")
            self.add_issue("ISSUE", "  - KILL_SWITCH_ENABLED or NO_NEW_TRADES is true")
            self.add_issue("ISSUE", "  - Set these to false in .env or config.py")
    
    def generate_recommendations(self):
        """Generate actionable recommendations"""
        print("\n" + "="*80)
        print("6. RECOMMENDATIONS")
        print("="*80)
        
        if not Config.STATE_FILE.exists():
            print(" Run the system at least once to generate state file")
            return
        
        try:
            with open(Config.STATE_FILE, 'r') as f:
                state = json.load(f)
        except:
            print(" Cannot read state file")
            return
        
        phase0_done = state.get('phase0_done', False)
        phase1_done = state.get('phase1_done', False)
        sell_ce_ready = state.get('sell_ce_leg_ready', False)
        sell_pe_ready = state.get('sell_pe_leg_ready', False)
        
        if not phase0_done:
            print("\n RECOMMENDATION: Fix Phase 0 completion")
            print("   1. Enable DEBUG_MODE=true in config")
            print("   2. Run system during market hours")
            print("   3. Check logs for Phase 0 execution")
            print("   4. Verify spot LTP is available")
            print("   5. Verify strike selection completes")
        
        elif not phase1_done:
            print("\n RECOMMENDATION: Fix Phase 1 completion")
            print("   1. Check OTM delta selection is working")
            print("   2. Verify buy strike selection completes")
            print("   3. Check logs for Phase 1 execution")
            print("   4. Ensure Phase 1 window is long enough")
        
        elif not (sell_ce_ready and sell_pe_ready):
            print("\n RECOMMENDATION: Fix leg readiness")
            print("   1. Check why legs are not marked ready")
            print("   2. Verify lock_sell_ce_leg and lock_sell_pe_leg are called")
            print("   3. Check state update is persisting")
        
        else:
            print("\n RECOMMENDATION: Debug entry conditions")
            print("   1. Enable DEBUG_MODE=true in config")
            print("   2. Watch logs for [SELL_ENTRY_CHECK] messages")
            print("   3. Check if LTP is available")
            print("   4. Check if decay condition is met")
            print("   5. Consider lowering SELL_DECAY_TRIGGER")
            print(f"      Current: {Config.SELL_DECAY_TRIGGER}, Try: 1.0 or 1.5")
    
    def print_summary(self):
        """Print diagnostic summary"""
        print("\n" + "="*80)
        print("DIAGNOSTIC SUMMARY")
        print("="*80)
        
        if self.issues:
            print(f"\n CRITICAL ISSUES FOUND: {len(self.issues)}")
            for issue in self.issues:
                print(f"  {issue}")
        else:
            print("\n No critical issues found")
        
        if self.warnings:
            print(f"\n  WARNINGS: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"  {warning}")
        
        print(f"\n  INFORMATION: {len(self.info)} items logged")
        
        print("\n" + "="*80)
        if self.issues:
            print(" SYSTEM HAS BLOCKING ISSUES - Fix critical issues first")
        elif self.warnings:
            print("  SYSTEM MAY HAVE ISSUES - Review warnings")
        else:
            print(" SYSTEM CONFIGURATION LOOKS OK - Check logs for runtime issues")
        print("="*80)

def main():
    print("="*80)
    print("TRADE ENTRY DIAGNOSTIC TOOL")
    print("="*80)
    print("This tool identifies why trades are not executing\n")
    
    diag = TradeDiagnostic()
    
    try:
        diag.check_configuration()
        diag.check_state_file()
        diag.check_timing()
        diag.analyze_entry_conditions()
        diag.check_common_issues()
        diag.generate_recommendations()
        diag.print_summary()
        
    except Exception as e:
        print(f"\n Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n Next Steps:")
    print("   1. Review the issues and warnings above")
    print("   2. Check system logs during market hours")
    print("   3. Enable DEBUG_MODE=true for detailed logging")
    print("   4. Run this diagnostic after each trading session")
    print("   5. If still stuck, share the diagnostic output\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
