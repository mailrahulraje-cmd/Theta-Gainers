"""
Delta Calculation and Validation Module

Implements:
- Broker delta as primary source
- Black-Scholes delta fallback calculation
- Simple price-change approximation as last resort
- Delta validation (-1 to +1 range)
- Source tracking for transparency
"""
import math
from typing import Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DeltaCalculator:
    """
    Robust delta calculation with multiple fallback methods
    Priority: Broker > Black-Scholes > Price-Change Approximation
    """
    
    # Risk-free rate assumption (can be configured)
    RISK_FREE_RATE = 0.07  # 7% annual
    
    @staticmethod
    def validate_delta(delta: Optional[float]) -> bool:
        """
        Validate delta is in valid range
        
        Args:
            delta: Delta value to validate
            
        Returns:
            True if valid, False otherwise
        """
        if delta is None:
            return False
        
        # Delta must be between -1 and +1
        if not (-1.0 <= delta <= 1.0):
            logger.warning(f"Invalid delta value: {delta} (outside [-1, 1])")
            return False
        
        return True
    
    @staticmethod
    def _norm_cdf(x: float) -> float:
        """
        Cumulative distribution function for standard normal distribution
        Approximation using error function
        """
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    
    @staticmethod
    def black_scholes_delta(spot: float, strike: float, time_to_expiry: float,
                           volatility: float, option_type: str,
                           risk_free_rate: float = None) -> Optional[float]:
        """
        Calculate delta using Black-Scholes model
        
        Args:
            spot: Current spot price
            strike: Strike price
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility (annual, as decimal, e.g., 0.15 for 15%)
            option_type: "CE" or "PE"
            risk_free_rate: Annual risk-free rate (default: class constant)
            
        Returns:
            Delta value or None if calculation fails
        """
        if risk_free_rate is None:
            risk_free_rate = DeltaCalculator.RISK_FREE_RATE
        
        try:
            # Handle edge cases
            if spot <= 0 or strike <= 0:
                logger.warning(f"Invalid spot/strike: spot={spot}, strike={strike}")
                return None
            
            if time_to_expiry <= 0:
                # At expiration or past
                if option_type == "CE":
                    return 1.0 if spot > strike else 0.0
                else:  # PE
                    return -1.0 if spot < strike else 0.0
            
            if volatility <= 0:
                logger.warning(f"Invalid volatility: {volatility}")
                return None
            
            # Black-Scholes d1 calculation
            d1 = (math.log(spot / strike) + 
                  (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) / \
                 (volatility * math.sqrt(time_to_expiry))
            
            # Calculate delta
            if option_type == "CE":
                delta = DeltaCalculator._norm_cdf(d1)
            elif option_type == "PE":
                delta = DeltaCalculator._norm_cdf(d1) - 1.0
            else:
                logger.warning(f"Invalid option_type: {option_type}")
                return None
            
            # Validate result
            if DeltaCalculator.validate_delta(delta):
                return delta
            else:
                return None
                
        except Exception as e:
            logger.error(f"Black-Scholes delta calculation error: {e}")
            return None
    
    @staticmethod
    def price_change_delta(current_price: float, previous_price: float,
                          spot_change: float, option_type: str) -> Optional[float]:
        """
        Approximate delta from price changes
        Delta  Option_Price / Spot_Price
        
        Args:
            current_price: Current option price
            previous_price: Previous option price
            spot_change: Spot price change (current - previous)
            option_type: "CE" or "PE"
            
        Returns:
            Approximate delta or None if calculation fails
        """
        try:
            if abs(spot_change) < 0.01:  # Avoid division by very small numbers
                return None
            
            option_change = current_price - previous_price
            delta = option_change / spot_change
            
            # Adjust sign for PE
            if option_type == "PE" and delta > 0:
                delta = -delta
            
            # Validate and clamp
            if abs(delta) > 1.0:
                delta = max(min(delta, 1.0), -1.0)
                logger.warning(f"Price-change delta clamped: {delta}")
            
            if DeltaCalculator.validate_delta(delta):
                return delta
            else:
                return None
                
        except Exception as e:
            logger.error(f"Price-change delta calculation error: {e}")
            return None
    
    @staticmethod
    def get_time_to_expiry(expiry_date: datetime, current_time: datetime = None) -> float:
        """
        Calculate time to expiry in years
        
        Args:
            expiry_date: Option expiry datetime
            current_time: Current datetime (default: now)
            
        Returns:
            Time to expiry in years
        """
        if current_time is None:
            current_time = datetime.now(expiry_date.tzinfo)
        
        time_delta = expiry_date - current_time
        
        # Convert to years (365.25 days per year)
        years = time_delta.total_seconds() / (365.25 * 24 * 3600)
        
        return max(0.0, years)  # Ensure non-negative


class RobustDeltaProvider:
    """
    Provides delta values with automatic fallback and source tracking
    """
    
    def __init__(self, default_volatility: float = 0.15):
        """
        Initialize delta provider
        
        Args:
            default_volatility: Default IV to use (15% annual = 0.15)
        """
        self.default_volatility = default_volatility
        self.calculator = DeltaCalculator()
        
        # Track delta sources for logging
        self.source_counts = {
            "broker": 0,
            "black_scholes": 0,
            "price_change": 0,
            "failed": 0
        }
    
    def get_delta(self, 
                  broker_delta: Optional[float],
                  spot: float,
                  strike: float,
                  option_type: str,
                  expiry_date: datetime,
                  current_price: Optional[float] = None,
                  previous_price: Optional[float] = None,
                  spot_change: Optional[float] = None,
                  volatility: Optional[float] = None) -> Tuple[Optional[float], str]:
        """
        Get delta with automatic fallback
        
        Priority:
        1. Broker-provided delta (if valid)
        2. Black-Scholes calculation
        3. Price-change approximation
        
        Args:
            broker_delta: Delta from broker feed
            spot: Current spot price
            strike: Strike price
            option_type: "CE" or "PE"
            expiry_date: Option expiry datetime
            current_price: Current option price (for price-change method)
            previous_price: Previous option price (for price-change method)
            spot_change: Recent spot price change (for price-change method)
            volatility: Implied volatility (for BS method, default: class default)
            
        Returns:
            Tuple of (delta_value, source_name)
            source_name: "broker", "black_scholes", "price_change", or "failed"
        """
        # Method 1: Use broker delta if available and valid
        if broker_delta is not None and self.calculator.validate_delta(broker_delta):
            self.source_counts["broker"] += 1
            return broker_delta, "broker"
        
        if broker_delta is not None:
            logger.warning(f"Broker delta invalid: {broker_delta}, using fallback")
        
        # Method 2: Black-Scholes calculation
        try:
            time_to_expiry = self.calculator.get_time_to_expiry(expiry_date)
            iv = volatility if volatility is not None else self.default_volatility
            
            bs_delta = self.calculator.black_scholes_delta(
                spot=spot,
                strike=strike,
                time_to_expiry=time_to_expiry,
                volatility=iv,
                option_type=option_type
            )
            
            if bs_delta is not None:
                self.source_counts["black_scholes"] += 1
                logger.info(
                    f"Using Black-Scholes delta: {bs_delta:.4f} "
                    f"(S={spot:.2f}, K={strike}, T={time_to_expiry:.4f}y, IV={iv:.2%})"
                )
                return bs_delta, "black_scholes"
        except Exception as e:
            logger.warning(f"Black-Scholes delta calculation failed: {e}")
        
        # Method 3: Price-change approximation
        if (current_price is not None and previous_price is not None and 
            spot_change is not None):
            try:
                pc_delta = self.calculator.price_change_delta(
                    current_price=current_price,
                    previous_price=previous_price,
                    spot_change=spot_change,
                    option_type=option_type
                )
                
                if pc_delta is not None:
                    self.source_counts["price_change"] += 1
                    logger.info(
                        f"Using price-change delta: {pc_delta:.4f} "
                        f"(Opt={current_price-previous_price:.2f}, Spot={spot_change:.2f})"
                    )
                    return pc_delta, "price_change"
            except Exception as e:
                logger.warning(f"Price-change delta calculation failed: {e}")
        
        # All methods failed
        self.source_counts["failed"] += 1
        logger.error(
            f"All delta calculation methods failed for {strike} {option_type}. "
            f"Broker={broker_delta}, Spot={spot}, Strike={strike}"
        )
        return None, "failed"
    
    def get_stats(self) -> dict:
        """Get delta source statistics"""
        total = sum(self.source_counts.values())
        if total == 0:
            return self.source_counts.copy()
        
        return {
            source: {
                "count": count,
                "percent": f"{100.0 * count / total:.1f}%"
            }
            for source, count in self.source_counts.items()
        }
    
    def log_stats(self):
        """Log delta source statistics"""
        stats = self.get_stats()
        logger.info("Delta Source Statistics:")
        for source, data in stats.items():
            if isinstance(data, dict):
                logger.info(f"  {source}: {data['count']} ({data['percent']})")
            else:
                logger.info(f"  {source}: {data}")    
    def scan_strikes_with_bounds(self, 
                                  options: list,
                                  target_delta: float,
                                  max_attempts: int,
                                  max_time_seconds: float) -> Optional[dict]:
        """
        Scan a list of options to find one with delta matching target_delta.
        CRITICAL: Bounded by both max_attempts and max_time_seconds to prevent infinite loops.
        
        Args:
            options: List of option dicts with 'token', 'symbol', 'strike', 'ltp' keys
            target_delta: Target delta value (e.g., 0.22 for CE, -0.22 for PE)
            max_attempts: Maximum number of options to scan
            max_time_seconds: Maximum total time to spend scanning
            
        Returns:
            dict with best matching option or None if not found within bounds
        """
        import time
        start_time = time.time()
        best_option = None
        min_score = float('inf')
        scan_count = 0
        
        for opt in options:
            # TIME GUARD: Stop if exceeded max time
            elapsed = time.time() - start_time
            if elapsed > max_time_seconds:
                logger.warning(f"DELTA_SCAN: Time limit ({max_time_seconds}s) reached after scanning {scan_count} options")
                if best_option is None:
                    logger.error("DELTA_SCAN_FAILED: No matching delta found within time limit")
                break
            
            # ATTEMPT GUARD: Stop if exceeded max attempts
            if scan_count >= max_attempts:
                logger.warning(f"DELTA_SCAN: Max attempts ({max_attempts}) reached")
                if best_option is None:
                    logger.error("DELTA_SCAN_FAILED: No matching delta found within max attempts")
                break
            
            try:
                # Skip if no delta available
                if opt.get('delta') is None:
                    continue
                
                scan_count += 1
                delta = opt['delta']
                score = abs(delta - target_delta)
                
                # Check if within bounds and better than current best
                if score < min_score:
                    min_score = score
                    best_option = opt.copy()
            
            except Exception as e:
                logger.debug(f"DELTA_SCAN: Error processing option {opt.get('symbol')}: {e}")
                continue
        
        if best_option is None:
            logger.error(f"DELTA_SCAN_FAILED: No matching delta found (scanned {scan_count} options in {time.time()-start_time:.1f}s)")
        
        return best_option