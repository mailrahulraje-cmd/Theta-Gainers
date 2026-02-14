import os
import csv
import threading
from datetime import datetime, date
from .logger import logger

class TickRecorder:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.current_file = None
        self.current_writer = None
        self.current_date = None
        self.file_lock = threading.Lock()
        logger.info(f" Tick recorder: {base_dir}")
    
            
    def _rotate_file(self, new_date: date):
        if self.current_file:
            self.current_file.close()
        filename = f"ticks_{new_date.strftime('%Y%m%d')}.csv"
        filepath = os.path.join(self.base_dir, filename)
        file_exists = os.path.exists(filepath)
        self.current_file = open(filepath, 'a', newline='', encoding='utf-8')
        self.current_writer = csv.writer(self.current_file)
        if not file_exists:
            self.current_writer.writerow(['timestamp', 'token', 'symbol', 'ltp'])
            logger.info(f" Created: {filename}")
        else:
            logger.info(f" Appending: {filename}")
        self.current_date = new_date
    
    def record_tick(self, token: str, symbol: str, ltp: float, timestamp: datetime, delta: float = None, phase: str = "N/A"):
        try:
            with self.file_lock:
                tick_date = timestamp.date()
                if tick_date != self.current_date:
                    self._rotate_file(tick_date)
                
                if self.current_writer:
                    # Extended Columns: timestamp, token, symbol, ltp, delta, phase
                    self.current_writer.writerow([
                        timestamp.isoformat(), 
                        token, 
                        symbol, 
                        f"{ltp:.2f}" if ltp else "0.00", 
                        f"{delta:.4f}" if delta is not None else "",
                        phase
                    ])
                    self.current_file.flush()
        except Exception as e:
            logger.error(f"Record tick failed: {e}")
    
    
    
    def close(self):
        with self.file_lock:
            if self.current_file:
                self.current_file.close()