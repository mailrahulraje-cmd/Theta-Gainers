from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class OptionLeg:
    token: str
    strike: int
    symbol: str
    ltp: float
    delta: Optional[float] = None
    qty: Optional[int] = None
    option_type: Optional[str] = None  # 'CE' or 'PE'

    def to_dict(self) -> Dict:
        return {
            'token': self.token,
            'strike': self.strike,
            'symbol': self.symbol,
            'ltp': self.ltp,
            'delta': self.delta,
            'qty': self.qty,
            'option_type': self.option_type
        }
