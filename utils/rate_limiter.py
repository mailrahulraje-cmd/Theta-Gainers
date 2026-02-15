"""
API Rate Limiter - Thread-safe rate limiting for API calls.

Enforces API_RATE_LIMIT_PER_SECOND to prevent spamming brokers.
Uses token bucket algorithm for smooth rate limiting.
"""

import time
import threading
from typing import Optional


class RateLimiter:
    """
    Token bucket rate limiter.
    
    Allows bursts up to burst_size, then throttles to rate_per_second.
    Thread-safe.
    """
    
    def __init__(self, rate_per_second: float = 2.0, burst_size: Optional[int] = None):
        """
        Initialize rate limiter.
        
        Args:
            rate_per_second: Target rate (calls per second)
            burst_size: Max tokens in bucket (default: rate_per_second)
        """
        self.rate_per_second = float(rate_per_second)
        self.burst_size = burst_size or int(max(1, rate_per_second))
        
        self.tokens = float(self.burst_size)  # Start with full bucket
        self.last_update = time.monotonic()
        self.lock = threading.Lock()
    
    def wait_if_needed(self) -> float:
        """
        Block if needed to enforce rate limit.
        
        Returns:
            float: Time actually slept (seconds)
        """
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            
            # Refill tokens based on elapsed time
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate_per_second
            )
            self.last_update = now
            
            # If we have tokens, consume one and return immediately
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return 0.0
            
            # Otherwise, sleep until we have one token
            sleep_time = (1.0 - self.tokens) / self.rate_per_second
            slept = 0.0
            
            # Sleep in small increments to avoid blocking too long
            while slept < sleep_time:
                actual_sleep = min(0.01, sleep_time - slept)
                time.sleep(actual_sleep)
                slept += actual_sleep
            
            # Update after sleep
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate_per_second
            )
            self.last_update = now
            
            # Consume token
            self.tokens -= 1.0
            
            return slept
    
    def reset(self):
        """Reset rate limiter to initial state"""
        with self.lock:
            self.tokens = float(self.burst_size)
            self.last_update = time.monotonic()


class GlobalRateLimiter:
    """
    Global singleton rate limiter for all API calls.
    Tracks calls across order placement, data fetch, and status checks.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, rate_per_second: float = 2.0):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, rate_per_second: float = 2.0):
        if self._initialized:
            return
        
        self._limiter = RateLimiter(rate_per_second, burst_size=int(max(1, rate_per_second)))
        self._initialized = True
    
    def wait_if_needed(self) -> float:
        """Wait if rate limit exceeded"""
        return self._limiter.wait_if_needed()
    
    def reset(self):
        """Reset rate limiter"""
        self._limiter.reset()


def get_global_rate_limiter(rate_per_second: float = 2.0) -> GlobalRateLimiter:
    """Get or create global rate limiter instance"""
    return GlobalRateLimiter(rate_per_second)
