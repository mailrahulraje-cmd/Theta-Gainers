import csv
import threading
from datetime import datetime
from typing import Dict, Optional, List, Any
from config import Config
from utils.logger import logger
from utils.delta_utils import RobustDeltaProvider

class InstrumentMaster:
    def __init__(self, csv_path: str):
        self.instruments = {}
        self._live_data = {} # Stores {token: {ltp, delta, timestamp}}
        self._lock = threading.Lock()
        
        # Initialize delta calculator with default IV from config (15%)
        self.delta_provider = RobustDeltaProvider(default_volatility=0.15)
        
        # Track spot price for delta calculation
        self._spot_price = None
        self._spot_token = None
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                token = row.get('token')
                if token:
                    self.instruments[token] = row
        logger.info(f" Loaded {len(self.instruments)} instruments")

    def update_snapshot(self, token: str, ltp: float = None, delta: float = None):
        """Updates the live market snapshot for a token with automatic delta calculation."""
        token_str = str(token)  # Force string to match CSV keys and get_snapshot
        with self._lock:
            if token_str not in self._live_data:
                self._live_data[token_str] = {"ltp": 0.0, "delta": None, "ts": None}
            
            if ltp is not None: 
                self._live_data[token_str]["ltp"] = ltp
            
            # Track spot price for delta calculations
            inst = self.instruments.get(token_str)
            if inst and inst.get('symbol') == 'Nifty 50':
                self._spot_price = ltp
                self._spot_token = token_str
            
            # Calculate delta if this is an option and we have spot price
            if delta is None and inst and ltp is not None and ltp > 0 and self._spot_price:
                calculated_delta = self._calculate_delta_for_option(inst, ltp)
                if calculated_delta is not None:
                    delta = calculated_delta
            
            if delta is not None: 
                self._live_data[token_str]["delta"] = delta
            
            self._live_data[token_str]["ts"] = datetime.now()
    
    def _calculate_delta_for_option(self, inst: Dict, ltp: float) -> Optional[float]:
        """Calculate Black-Scholes delta for an option"""
        try:
            # Check if this is an option
            symbol = inst.get('symbol', '')
            if not (symbol.endswith('CE') or symbol.endswith('PE')):
                return None
            
            # Extract strike price
            strike_str = inst.get('strike')
            if not strike_str:
                return None
            strike = float(strike_str) / Config.STRIKE_UNIT  # Convert using Config.STRIKE_UNIT
            
            # Get expiry date
            expiry_str = inst.get('expiry')
            if not expiry_str:
                return None
            
            # Parse expiry date
            expiry_date = None
            for fmt in ['%d%b%Y', '%d%b%y']:
                try:
                    expiry_date = datetime.strptime(expiry_str, fmt)
                    # Set to 3:30 PM IST on expiry day
                    expiry_date = expiry_date.replace(hour=15, minute=30, second=0)
                    break
                except:
                    pass
            
            if not expiry_date or not self._spot_price:
                return None
            
            # Determine option type
            option_type = 'CE' if symbol.endswith('CE') else 'PE'
            
            # Calculate delta using Black-Scholes
            delta, source = self.delta_provider.get_delta(
                broker_delta=None,  # Broker doesn't provide
                spot=self._spot_price,
                strike=strike,
                option_type=option_type,
                expiry_date=expiry_date,
                current_price=ltp
            )
            
            return delta
            
        except Exception as e:
            logger.debug(f"Delta calculation failed for {inst.get('symbol')}: {e}")
            return None
        
    def get_snapshot(self, token: str) -> Dict[str, Any]:
        with self._lock:
            return self._live_data.get(str(token), {"ltp": 0.0, "delta": None, "ts": None})

    def get_delta(self, token: str) -> Optional[float]:
        return self.get_snapshot(token).get("delta")

    def get_ltp(self, token: str) -> float:
        return self.get_snapshot(token).get("ltp", 0.0)

    # ... (keep existing find_spot, find_option, find_options_in_range methods)    
    def find_spot(self) -> Optional[Dict]:
        for token, inst in self.instruments.items():
            if inst.get('symbol') == 'Nifty 50' and inst.get('exch_seg') == Config.SPOT_EXCHANGE:
                return inst
        return None
    
    def find_option(self, strike: int, option_type: str, expiry: str) -> Optional[Dict]:
        strike_fmt = int(strike * 100)
        for token, inst in self.instruments.items():
            if (inst.get('name') == Config.UNDERLYING_SYMBOL and
                inst.get('exch_seg') == Config.EXCHANGE and
                inst.get('expiry') == expiry):
                try:
                    if int(float(inst.get('strike', '0'))) == strike_fmt and inst.get('symbol', '').endswith(option_type):
                        return inst
                except:
                    pass
        return None
    
    def find_options_in_range(self, min_strike: int, max_strike: int, option_type: str, expiry: str) -> List[Dict]:
        options = []
        for token, inst in self.instruments.items():
            if (inst.get('name') == Config.UNDERLYING_SYMBOL and
                inst.get('exch_seg') == Config.EXCHANGE and
                inst.get('expiry') == expiry):
                try:
                    strike_price = int(float(inst.get('strike', '0'))) / Config.STRIKE_UNIT
                    if min_strike <= strike_price <= max_strike and inst.get('symbol', '').endswith(option_type):
                        inst_copy = inst.copy()
                        inst_copy['strike_price'] = strike_price
                        options.append(inst_copy)
                except:
                    pass
        return sorted(options, key=lambda x: x['strike_price'])
    
    def get_nearest_expiry(self) -> Optional[str]:
        expiries = set()
        for inst in self.instruments.values():
            if inst.get('name') == Config.UNDERLYING_SYMBOL and inst.get('exch_seg') == Config.EXCHANGE:
                exp = inst.get('expiry')
                if exp and exp.strip():
                    expiries.add(exp)
        if not expiries:
            return None
        def parse_exp(e):
            for fmt in ['%d%b%Y', '%d%b%y']:
                try:
                    return datetime.strptime(e, fmt)
                except:
                    pass
            return datetime(2099, 12, 31)
        return sorted(expiries, key=parse_exp)[0]
    
    def get_lot_size(self, token: str) -> int:
        inst = self.instruments.get(token)
        if inst:
            try:
                return int(float(inst.get('lotsize', 1)))
            except:
                return 1
        return 1
