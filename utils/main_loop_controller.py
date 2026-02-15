"""
Main Loop Controller - Enforces fixed iteration frequency and prevents API spamming.

Uses monotonic clock for precise timing, avoiding clock skew issues.
Single responsibility: Ensure main loop iteration doesn't exceed desired frequency.
"""

import time
from typing import Callable, Optional
from config import Config
from utils.logger import logger


class MainLoopController:
    """
    Enforces minimum iteration interval for main loop.
    
    Usage:
        controller = MainLoopController()
        
        while True:
            # Do work...
            
            controller.sleep_remaining()  # Enforces MAIN_LOOP_INTERVAL_SECONDS
    
    Provides:
    - Monotonic clock timing (immune to system time adjustments)
    - Precise interval enforcement
    - Iteration counting and statistics
    """
    
    def __init__(self, interval_seconds: Optional[float] = None):
        """
        Initialize loop controller.
        
        Args:
            interval_seconds: Target iteration interval in seconds.
                             Defaults to Config.MAIN_LOOP_INTERVAL_SECONDS
        """
        self.interval_seconds = interval_seconds or Config.MAIN_LOOP_INTERVAL_SECONDS
        
        # Monotonic clock tracking (immune to system time adjustments)
        self.iteration_start_time = time.monotonic()
        self.iteration_count = 0
        self.total_work_time = 0.0  # Time spent doing work
        self.total_sleep_time = 0.0  # Time spent sleeping
        self.last_log_time = time.monotonic()
        self.last_log_count = 0
        
        logger.info(f"[INIT] MainLoopController: interval_seconds={self.interval_seconds:.3f}s")
    
    def start_iteration(self):
        """Mark start of current iteration"""
        self.iteration_start_time = time.monotonic()
    
    def sleep_remaining(self) -> float:
        """
        Sleep for remaining time to enforce interval.
        
        Returns:
            float: Time actually slept (seconds)
        """
        now = time.monotonic()
        elapsed_work = now - self.iteration_start_time
        
        if elapsed_work >= self.interval_seconds:
            # Work took longer than interval - no sleep needed
            # Log warning if significantly over
            if elapsed_work > self.interval_seconds * 1.5:
                logger.debug(
                    f"[WARN] Iteration {self.iteration_count}: "
                    f"work took {elapsed_work:.3f}s "
                    f"(target: {self.interval_seconds:.3f}s)"
                )
            
            self.iteration_count += 1
            self._log_stats_if_needed()
            return 0.0
        
        # Calculate sleep time
        sleep_time = self.interval_seconds - elapsed_work
        
        # Sleep
        time.sleep(sleep_time)
        
        # Track statistics
        self.total_work_time += elapsed_work
        self.total_sleep_time += sleep_time
        self.iteration_count += 1
        
        self._log_stats_if_needed()
        
        return sleep_time
    
    def _log_stats_if_needed(self):
        """Log statistics every 60 iterations"""
        if self.iteration_count - self.last_log_count >= 60:
            elapsed_total = time.monotonic() - self.last_log_time
            actual_interval = elapsed_total / (self.iteration_count - self.last_log_count)
            
            logger.debug(
                f"[STATS] Last 60 iterations: "
                f"interval_actual={actual_interval:.3f}s, "
                f"interval_target={self.interval_seconds:.3f}s, "
                f"efficiency={(self.total_work_time / (self.total_work_time + self.total_sleep_time) * 100):.1f}%"
            )
            
            self.last_log_time = time.monotonic()
            self.last_log_count = self.iteration_count
            self.total_work_time = 0.0
            self.total_sleep_time = 0.0
    
    def get_interval_seconds(self) -> float:
        """Get current target interval"""
        return self.interval_seconds
    
    def set_interval_seconds(self, new_interval: float):
        """Set new target interval (useful for dynamic adjustment)"""
        if new_interval <= 0:
            logger.warning(f"[WARN] Invalid interval: {new_interval}, keeping {self.interval_seconds}")
            return
        
        old = self.interval_seconds
        self.interval_seconds = float(new_interval)
        logger.info(f"[INFO] Loop interval changed: {old:.3f}s -> {self.interval_seconds:.3f}s")
    
    def get_stats(self) -> dict:
        """Return current statistics"""
        return {
            'iteration_count': self.iteration_count,
            'interval_seconds': self.interval_seconds,
            'total_work_time': self.total_work_time,
            'total_sleep_time': self.total_sleep_time
        }
