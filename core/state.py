import json
import os
import threading
from datetime import date
from typing import Dict, Any
from utils.logger import logger
from contract import StateProtocol
from config import Config

class StrategyState:
    def __init__(self, state_file: str, notifier=None):
        self.state_file = state_file
        self.state = self._load_state()
        self.lock = threading.Lock()
        self.notifier = notifier
        self._normalize_legacy_state()  # Normalize old state formats
        self._cleanup_daily_state()
    
    def _load_state(self) -> Dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state file {self.state_file}: {e}")
                return {}
        return {}
    
    def _normalize_legacy_state(self):
        """
        Detect and normalize legacy flat state format to structured format.
        CRITICAL: Backward compatible - preserves all information while adding new structure.
        
        Legacy format: flat boolean flags like 'sell_ce_entered', 'buy_ce_entered'
        New format: structured 'legs' object with entry/token/sl/qty per leg
        """
        if not self.state:
            return
        
        # Check if we need normalization (has legacy flat flags but no legs object)
        has_legacy_flags = any(k.endswith('_entered') or k.endswith('_leg_ready') 
                               for k in self.state.keys())
        has_new_structure = 'legs' in self.state and isinstance(self.state['legs'], dict)
        
        if has_legacy_flags and not has_new_structure:
            logger.info(" Normalizing legacy state format to structured legs")
            
            # Create structured legs object from legacy flags
            self.state['legs'] = {
                'sell_ce': {
                    'entered': self.state.get('sell_ce_entered', False),
                    'token': self.state.get('sell_ce_token'),
                    'sl': self.state.get('sell_ce_sl'),
                    'qty': -self.state.get('sell_ce_qty', 0)  # Negative for short
                },
                'sell_pe': {
                    'entered': self.state.get('sell_pe_entered', False),
                    'token': self.state.get('sell_pe_token'),
                    'sl': self.state.get('sell_pe_sl'),
                    'qty': -self.state.get('sell_pe_qty', 0)
                },
                'buy_ce': {
                    'entered': self.state.get('buy_ce_entered', False),
                    'token': self.state.get('buy_ce_token'),
                    'sl': self.state.get('buy_ce_sl'),
                    'qty': self.state.get('buy_ce_qty', 0)
                },
                'buy_pe': {
                    'entered': self.state.get('buy_pe_entered', False),
                    'token': self.state.get('buy_pe_token'),
                    'sl': self.state.get('buy_pe_sl'),
                    'qty': self.state.get('buy_pe_qty', 0)
                }
            }
            
            # Also update phase if missing
            if 'phase' not in self.state:
                self.state['phase'] = 'INIT'
            
            logger.info(" Legacy state normalized - structured 'legs' object created")
            # Create trade_state single-source-of-truth for leg lifecycle
            trade_state = self.state.get('trade_state', {
                'sell_ce': 'IDLE', 'sell_pe': 'IDLE', 'buy_ce': 'IDLE', 'buy_pe': 'IDLE'
            })

            # Map legacy flags into trade_state
            if self.state.get('sell_ce_entered'):
                trade_state['sell_ce'] = 'ENTERED'
            elif self.state.get('sell_ce_leg_ready'):
                trade_state['sell_ce'] = 'READY'

            if self.state.get('sell_pe_entered'):
                trade_state['sell_pe'] = 'ENTERED'
            elif self.state.get('sell_pe_leg_ready'):
                trade_state['sell_pe'] = 'READY'

            if self.state.get('buy_ce_entered'):
                trade_state['buy_ce'] = 'ENTERED'
            elif self.state.get('buy_ce_leg_ready'):
                trade_state['buy_ce'] = 'READY'

            if self.state.get('buy_pe_entered'):
                trade_state['buy_pe'] = 'ENTERED'
            elif self.state.get('buy_pe_leg_ready'):
                trade_state['buy_pe'] = 'READY'

            self.state['trade_state'] = trade_state
            self._save_state()


    def lock_sell_ce_leg(self, data: Dict) -> bool:
        """Lock SELL CE leg independently. Returns True if newly locked."""
        # Accept either dict or OptionLeg
        try:
            from strategy.option_leg import OptionLeg
            if isinstance(data, OptionLeg):
                data = data.to_dict()
        except Exception:
            pass

        with self.lock:
            if self.state.get('sell_ce_leg_ready'):
                return False
            self.state['sell_ce_token'] = data['token']
            self.state['sell_ce_strike'] = data['strike']
            self.state['sell_ce_ref_premium'] = data['ltp']
            self.state['sell_ce_symbol'] = data['symbol']
            self.state['sell_ce_leg_ready'] = True
            # Keep trade_state authoritative
            ts = self.state.get('trade_state', {})
            ts.setdefault('sell_ce', 'IDLE')
            ts['sell_ce'] = 'READY'
            self.state['trade_state'] = ts
            self._save_state()
            logger.info(f" SELL CE leg ready: {data['symbol']} @ {data['ltp']:.2f}")
        
        # FIXED: Notifier call MOVED OUTSIDE lock to prevent deadlock
        if self.notifier:
            try:
                message = (
                    f" <b>SELL CE Locked</b>\n"
                    f" Strike: <b>{data['strike']}</b>\n"
                    f" Reference Price: <code>{data['ltp']:.2f}</code>\n"
                    f" Symbol: {data['symbol']}"
                )
                # FIX: Non-blocking notifier call
                import threading
                threading.Thread(
                    target=self.notifier.send_strike_selection,
                    args=(message,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to send SELL CE lock notification: {e}")
        
        return True
    
    def lock_sell_pe_leg(self, data: Dict) -> bool:
        """Lock SELL PE leg independently. Returns True if newly locked."""
        try:
            from strategy.option_leg import OptionLeg
            if isinstance(data, OptionLeg):
                data = data.to_dict()
        except Exception:
            pass

        with self.lock:
            if self.state.get('sell_pe_leg_ready'):
                return False
            self.state['sell_pe_token'] = data['token']
            self.state['sell_pe_strike'] = data['strike']
            self.state['sell_pe_ref_premium'] = data['ltp']
            self.state['sell_pe_symbol'] = data['symbol']
            self.state['sell_pe_leg_ready'] = True
            ts = self.state.get('trade_state', {})
            ts.setdefault('sell_pe', 'IDLE')
            ts['sell_pe'] = 'READY'
            self.state['trade_state'] = ts
            self._save_state()
            logger.info(f" SELL PE leg ready: {data['symbol']} @ {data['ltp']:.2f}")
        
        # FIXED: Notifier call MOVED OUTSIDE lock to prevent deadlock
        if self.notifier:
            try:
                message = (
                    f" <b>SELL PE Locked</b>\n"
                    f" Strike: <b>{data['strike']}</b>\n"
                    f" Reference Price: <code>{data['ltp']:.2f}</code>\n"
                    f" Symbol: {data['symbol']}"
                )
                # FIX: Non-blocking notifier call
                import threading
                threading.Thread(
                    target=self.notifier.send_strike_selection,
                    args=(message,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to send SELL PE lock notification: {e}")
        
        return True
    
    def lock_buy_ce_leg(self, data: Dict) -> bool:
        """Lock BUY CE leg independently. Returns True if newly locked."""
        try:
            from strategy.option_leg import OptionLeg
            if isinstance(data, OptionLeg):
                data = data.to_dict()
        except Exception:
            pass

        with self.lock:
            if self.state.get('buy_ce_leg_ready'):
                return False
            self.state['buy_ce_token'] = data['token']
            self.state['buy_ce_strike'] = data['strike']
            self.state['buy_ce_delta_at_selection'] = data.get('delta')
            self.state['buy_ce_ref_premium'] = data['ltp']
            self.state['buy_ce_symbol'] = data['symbol']
            self.state['buy_ce_leg_ready'] = True
            ts = self.state.get('trade_state', {})
            ts.setdefault('buy_ce', 'IDLE')
            ts['buy_ce'] = 'READY'
            self.state['trade_state'] = ts
            self._save_state()
            logger.info(f" BUY CE leg ready: {data['symbol']} (:{data.get('delta', 'N/A')}) @ {data['ltp']:.2f}")
        
        # FIXED: Notifier call MOVED OUTSIDE lock to prevent deadlock
        if self.notifier:
            try:
                # FIX: Check 'delta' in data to preserve 0.0 values
                delta_info = f" (: {data['delta']})" if 'delta' in data and data['delta'] is not None else ""
                message = (
                    f" <b>BUY CE Locked</b>\n"
                    f" Strike: <b>{data['strike']}</b>\n"
                    f" Reference Price: <code>{data['ltp']:.2f}</code>\n"
                    f" Symbol: {data['symbol']}{delta_info}"
                )
                import threading
                threading.Thread(
                    target=self.notifier.send_strike_selection,
                    args=(message,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to send BUY CE lock notification: {e}")
        
        return True
    
    def lock_buy_pe_leg(self, data: Dict) -> bool:
        """Lock BUY PE leg independently. Returns True if newly locked."""
        try:
            from strategy.option_leg import OptionLeg
            if isinstance(data, OptionLeg):
                data = data.to_dict()
        except Exception:
            pass

        with self.lock:
            if self.state.get('buy_pe_leg_ready'):
                return False
            self.state['buy_pe_token'] = data['token']
            self.state['buy_pe_strike'] = data['strike']
            self.state['buy_pe_delta_at_selection'] = data.get('delta')
            self.state['buy_pe_ref_premium'] = data['ltp']
            self.state['buy_pe_symbol'] = data['symbol']
            self.state['buy_pe_leg_ready'] = True
            ts = self.state.get('trade_state', {})
            ts.setdefault('buy_pe', 'IDLE')
            ts['buy_pe'] = 'READY'
            self.state['trade_state'] = ts
            self._save_state()
            logger.info(f" BUY PE leg ready: {data['symbol']} (:{data.get('delta', 'N/A')}) @ {data['ltp']:.2f}")
        
        # FIXED: Notifier call MOVED OUTSIDE lock to prevent deadlock
        if self.notifier:
            try:
                # FIX: Check 'delta' in data to preserve 0.0 values
                delta_info = f" (: {data['delta']})" if 'delta' in data and data['delta'] is not None else ""
                message = (
                    f" <b>BUY PE Locked</b>\n"
                    f" Strike: <b>{data['strike']}</b>\n"
                    f" Reference Price: <code>{data['ltp']:.2f}</code>\n"
                    f" Symbol: {data['symbol']}{delta_info}"
                )
                import threading
                threading.Thread(
                    target=self.notifier.send_strike_selection,
                    args=(message,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to send BUY PE lock notification: {e}")
        
        return True

    # ... (rest of file)
    
    def _cleanup_daily_state(self):
        with self.lock:
            today = date.today().isoformat()
            last_run = self.state.get('last_run_date')
            if last_run and last_run != today:
                logger.info(f" New day reset")
                # FIX: Added '_phase1_attempt_count' & '_phase1_completed_without_hedges'
                # Old coupled flags
                for k in ['phase0_done', 'phase1_done', 'sell_ce_entered', 'sell_pe_entered', 
                         'buy_ce_entered', 'buy_pe_entered', 'sell_ce_exited', 'sell_pe_exited',
                         'buy_ce_exited', 'buy_pe_exited', 'squareoff_done', 'phase1_complete_time',
                         '_phase1_attempt_count', '_phase1_completed_without_hedges']:
                    self.state.pop(k, None)
                # New independent leg flags
                for k in ['sell_ce_leg_ready', 'sell_pe_leg_ready', 'buy_ce_leg_ready', 'buy_pe_leg_ready']:
                    self.state.pop(k, None)
                # Reset trade_state single source of truth
                if 'trade_state' in self.state:
                    self.state['trade_state'] = {
                        'sell_ce': 'IDLE', 'sell_pe': 'IDLE', 'buy_ce': 'IDLE', 'buy_pe': 'IDLE'
                    }
            elif last_run == today:
                logger.info(" Same day - preserving state")
            self.state['last_run_date'] = today
            self._save_state()
    
    def _save_state(self):
        """
        Atomic state save to prevent corruption.
        Uses temporary file + atomic rename for safety.
        """
        try:
            import os
            tmp_file = self.state_file + ".tmp"
            with open(tmp_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp_file, self.state_file)  # Atomic operation on POSIX systems
        except Exception as e:
            logger.error(f"State save failed: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            # Backwards-compatible mapping: legacy boolean flags are derived from 'trade_state'
            ts = self.state.get('trade_state', {})

            # SELL CE
            if key == 'sell_ce_leg_ready':
                val = ts.get('sell_ce')
                return (val in ('READY', 'ENTERED')) if val is not None else self.state.get(key, default)
            if key == 'sell_ce_entered':
                return (ts.get('sell_ce') == 'ENTERED') if ts.get('sell_ce') is not None else self.state.get(key, default)
            if key == 'sell_ce_exited':
                return (ts.get('sell_ce') == 'EXITED') if ts.get('sell_ce') is not None else self.state.get(key, default)

            # SELL PE
            if key == 'sell_pe_leg_ready':
                val = ts.get('sell_pe')
                return (val in ('READY', 'ENTERED')) if val is not None else self.state.get(key, default)
            if key == 'sell_pe_entered':
                return (ts.get('sell_pe') == 'ENTERED') if ts.get('sell_pe') is not None else self.state.get(key, default)
            if key == 'sell_pe_exited':
                return (ts.get('sell_pe') == 'EXITED') if ts.get('sell_pe') is not None else self.state.get(key, default)

            # BUY CE
            if key == 'buy_ce_leg_ready':
                val = ts.get('buy_ce')
                return (val in ('READY', 'ENTERED')) if val is not None else self.state.get(key, default)
            if key == 'buy_ce_entered':
                return (ts.get('buy_ce') == 'ENTERED') if ts.get('buy_ce') is not None else self.state.get(key, default)
            if key == 'buy_ce_exited':
                return (ts.get('buy_ce') == 'EXITED') if ts.get('buy_ce') is not None else self.state.get(key, default)

            # BUY PE
            if key == 'buy_pe_leg_ready':
                val = ts.get('buy_pe')
                return (val in ('READY', 'ENTERED')) if val is not None else self.state.get(key, default)
            if key == 'buy_pe_entered':
                return (ts.get('buy_pe') == 'ENTERED') if ts.get('buy_pe') is not None else self.state.get(key, default)
            if key == 'buy_pe_exited':
                return (ts.get('buy_pe') == 'EXITED') if ts.get('buy_pe') is not None else self.state.get(key, default)

            return self.state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        with self.lock:
            # If setting legacy booleans, translate into trade_state authoritative value
            ts = self.state.get('trade_state', {
                'sell_ce': 'IDLE', 'sell_pe': 'IDLE', 'buy_ce': 'IDLE', 'buy_pe': 'IDLE'
            })

            # Map legacy keys -> trade_state updates
            if key == 'sell_ce_leg_ready':
                if value:
                    ts['sell_ce'] = 'READY'
                else:
                    if ts.get('sell_ce') == 'READY':
                        ts['sell_ce'] = 'IDLE'
                self.state['trade_state'] = ts
            elif key == 'sell_ce_entered':
                if value:
                    ts['sell_ce'] = 'ENTERED'
                    self.state['trade_state'] = ts
            elif key == 'sell_ce_exited':
                if value:
                    ts['sell_ce'] = 'EXITED'
                    self.state['trade_state'] = ts

            elif key == 'sell_pe_leg_ready':
                if value:
                    ts['sell_pe'] = 'READY'
                else:
                    if ts.get('sell_pe') == 'READY':
                        ts['sell_pe'] = 'IDLE'
                self.state['trade_state'] = ts
            elif key == 'sell_pe_entered':
                if value:
                    ts['sell_pe'] = 'ENTERED'
                    self.state['trade_state'] = ts
            elif key == 'sell_pe_exited':
                if value:
                    ts['sell_pe'] = 'EXITED'
                    self.state['trade_state'] = ts

            elif key == 'buy_ce_leg_ready':
                if value:
                    ts['buy_ce'] = 'READY'
                else:
                    if ts.get('buy_ce') == 'READY':
                        ts['buy_ce'] = 'IDLE'
                self.state['trade_state'] = ts
            elif key == 'buy_ce_entered':
                if value:
                    ts['buy_ce'] = 'ENTERED'
                    self.state['trade_state'] = ts
            elif key == 'buy_ce_exited':
                if value:
                    ts['buy_ce'] = 'EXITED'
                    self.state['trade_state'] = ts

            elif key == 'buy_pe_leg_ready':
                if value:
                    ts['buy_pe'] = 'READY'
                else:
                    if ts.get('buy_pe') == 'READY':
                        ts['buy_pe'] = 'IDLE'
                self.state['trade_state'] = ts
            elif key == 'buy_pe_entered':
                if value:
                    ts['buy_pe'] = 'ENTERED'
                    self.state['trade_state'] = ts
            elif key == 'buy_pe_exited':
                if value:
                    ts['buy_pe'] = 'EXITED'
                    self.state['trade_state'] = ts

            # If directly setting trade_state, mirror to legacy flags for compatibility
            if key == 'trade_state' and isinstance(value, dict):
                self.state['trade_state'] = value
                # Mirror simple booleans for legacy consumers
                self.state['sell_ce_leg_ready'] = value.get('sell_ce') in ('READY', 'ENTERED')
                self.state['sell_ce_entered'] = value.get('sell_ce') == 'ENTERED'
                self.state['sell_pe_leg_ready'] = value.get('sell_pe') in ('READY', 'ENTERED')
                self.state['sell_pe_entered'] = value.get('sell_pe') == 'ENTERED'
                self.state['buy_ce_leg_ready'] = value.get('buy_ce') in ('READY', 'ENTERED')
                self.state['buy_ce_entered'] = value.get('buy_ce') == 'ENTERED'
                self.state['buy_pe_leg_ready'] = value.get('buy_pe') in ('READY', 'ENTERED')
                self.state['buy_pe_entered'] = value.get('buy_pe') == 'ENTERED'
                self._save_state()
                return

            # Default behavior: set key and save
            self.state[key] = value
            self._save_state()
    
    def update(self, updates: Dict[str, Any]) -> None:
        with self.lock:
            if Config.DEBUG_MODE:
                logger.debug(f"[STATE] Updating state: {updates}")
            self.state.update(updates)
            self._save_state()
            # Log important state changes always
            for key in ['sell_ce_entered', 'sell_pe_entered', 'buy_ce_entered', 'buy_pe_entered']:
                if key in updates:
                    logger.info(f"[STATE]  State updated: {key}={updates[key]}")