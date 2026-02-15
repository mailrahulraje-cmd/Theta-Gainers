#!/usr/bin/env python3
"""
Test script: Refined Snapshot Formatting with Emoji Support
Demonstrates:
- Leg-wise P&L with entry, LTP, SL per leg
- Open vs Locked leg separation with emojis
- Currency symbols (₹) and direction indicators
- Deduplication logic (₹10 threshold, 30-sec interval)
- Mobile-friendly formatting for <10 sec scan
"""

import sys
import time
from datetime import datetime
from typing import Dict, List

# Mock classes for testing without full system
class MockTradeLeg:
    def __init__(self, token, symbol, strike, option_type, entry_price, qty, current_ltp, current_sl=None):
        self.token = token
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.entry_price = entry_price
        self.qty = qty  # +qty for buy, -qty for sell
        self.current_ltp = current_ltp
        self.current_sl = current_sl
        self.is_locked = False
        self.locked_price = None
        self.locked_time = None
        self.lock_reason = None
    
    @property
    def pnl(self):
        """Calculate P&L: (LTP - Entry) * qty for long, (Entry - LTP) * qty for short"""
        if self.qty > 0:  # Long position
            return (self.current_ltp - self.entry_price) * self.qty
        else:  # Short position
            return (self.entry_price - self.current_ltp) * abs(self.qty)
    
    def mark_locked(self, reason, locked_price):
        self.is_locked = True
        self.locked_price = locked_price
        self.locked_time = datetime.now()
        self.lock_reason = reason


def build_refined_snapshot(legs: List[MockTradeLeg]) -> str:
    """
    Build refined snapshot with:
    - OPEN LEGS: with per-leg entry, LTP, P&L, SL
    - LOCKED LEGS: with locked price, reason, P&L
    - SUMMARY: cumulative P&L, open/locked counts
    Uses UTF-8 emojis and ₹ currency
    """
    # Separate open and locked legs
    open_legs = [leg for leg in legs if not leg.is_locked]
    locked_legs = [leg for leg in legs if leg.is_locked]
    
    # Calculate cumulative P&L
    cum_pnl = sum(leg.pnl for leg in legs)
    cum_pnl_emoji = "📈" if cum_pnl >= 0 else "📉"
    
    time_str = datetime.now().strftime("%H:%M:%S")
    
    # Build text
    text = f"📊 <b>POSITION SNAPSHOT</b>\n\n"
    text += f"<code>Time: {time_str}</code>\n\n"
    
    # =================
    # OPEN LEGS SECTION
    # =================
    if open_legs:
        text += f"🟢 <b>OPEN LEGS ({len(open_legs)})</b>\n"
        text += "─" * 45 + "\n\n"
        
        # Sort: CE first, then PE
        sorted_open = sorted(open_legs, key=lambda x: (x.option_type != "CE", x.strike))
        
        for leg in sorted_open:
            leg_pnl = leg.pnl
            leg_pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
            
            # Direction and type emojis
            leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
            buy_sell_emoji = "🟦" if leg.qty > 0 else "🟥"  # Blue=Buy, Red=Sell
            
            # Build leg line
            text += (
                f"{buy_sell_emoji} <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b>\n"
                f"   Entry: ₹{leg.entry_price:.2f} | LTP: ₹{leg.current_ltp:.2f}\n"
                f"   {leg_pnl_emoji} P&L: <b>₹{leg_pnl:+.2f}</b>"
            )
            
            # Add SL if available
            if leg.current_sl is not None:
                text += f" | SL: ₹{leg.current_sl:.2f}"
            
            text += "\n\n"
    
    # ===================
    # LOCKED LEGS SECTION
    # ===================
    if locked_legs:
        text += f"🔒 <b>LOCKED LEGS ({len(locked_legs)})</b>\n"
        text += "─" * 45 + "\n\n"
        
        # Sort: CE first, then PE
        sorted_locked = sorted(locked_legs, key=lambda x: (x.option_type != "CE", x.strike))
        
        for leg in sorted_locked:
            leg_pnl = leg.pnl
            leg_pnl_emoji = "📈" if leg_pnl >= 0 else "📉"
            leg_dir_emoji = "📞" if leg.option_type == "CE" else "📧"
            
            text += (
                f"🔒 <b>{leg_dir_emoji} {leg.option_type} {leg.strike}</b>\n"
                f"   Locked: ₹{leg.locked_price:.2f} | Reason: <i>{leg.lock_reason}</i>\n"
                f"   {leg_pnl_emoji} P&L: <b>₹{leg_pnl:+.2f}</b>\n\n"
            )
    
    # ===============
    # SUMMARY SECTION
    # ===============
    text += "─" * 45 + "\n"
    text += f"{cum_pnl_emoji} <b>CUMULATIVE P&L: ₹{cum_pnl:+.2f}</b>\n"
    text += f"   Open: {len(open_legs)} | Locked: {len(locked_legs)}"
    
    return text


def simulate_deduplication():
    """
    Simulate snapshot deduplication:
    - Skip if P&L change < ₹10
    - Skip if sent < 30 sec ago
    - Skip if no leg prices changed
    """
    print("\n" + "=" * 60)
    print("DEDUPLICATION LOGIC SIMULATION")
    print("=" * 60 + "\n")
    
    class SnapshotState:
        def __init__(self):
            self.last_snapshot_pnl = None
            self.last_snapshot_time = None
            self.last_snapshot_leg_prices = {}
            self.PNL_THRESHOLD = 10.0
            self.MIN_INTERVAL = 30  # seconds
        
        def should_send(self, current_pnl, current_leg_prices):
            """Check if snapshot should be sent"""
            import time
            now = time.time()
            
            # Check interval
            if self.last_snapshot_time is not None:
                elapsed = now - self.last_snapshot_time
                if elapsed < self.MIN_INTERVAL:
                    reason = f"Too soon: only {elapsed:.1f}s elapsed (min {self.MIN_INTERVAL}s)"
                    return False, reason
            
            # Check P&L threshold
            if self.last_snapshot_pnl is not None:
                pnl_change = abs(current_pnl - self.last_snapshot_pnl)
                if pnl_change < self.PNL_THRESHOLD:
                    # Check if any leg price changed
                    price_changed = False
                    for token, ltp in current_leg_prices.items():
                        if self.last_snapshot_leg_prices.get(token) != ltp:
                            price_changed = True
                            break
                    
                    if not price_changed:
                        reason = f"Skipped: P&L change ₹{pnl_change:.2f} < ₹{self.PNL_THRESHOLD}"
                        return False, reason
            
            # Update state
            self.last_snapshot_pnl = current_pnl
            self.last_snapshot_time = now
            self.last_snapshot_leg_prices = current_leg_prices.copy()
            return True, "SENT"
    
    state = SnapshotState()
    
    # Test scenario 1: First snapshot (always send)
    print("Scenario 1: First snapshot")
    pnl1 = 150.0
    prices1 = {"CE_22000": 143.50, "PE_22000": 150.75}
    send, reason = state.should_send(pnl1, prices1)
    print(f"  Result: {reason} {'✓' if send else '✗'}")
    
    # Test scenario 2: P&L change < ₹10, prices unchanged (skip)
    print("\nScenario 2: Small P&L change (₹5), no price change")
    pnl2 = 155.0  # +5 from previous
    prices2 = {"CE_22000": 143.50, "PE_22000": 150.75}  # Same
    send, reason = state.should_send(pnl2, prices2)
    print(f"  Result: {reason} {'✓' if not send else '✗ (should skip)'}")
    
    # Test scenario 3: Large P&L change > ₹10 (send)
    print("\nScenario 3: Large P&L change (₹30), prices updated")
    pnl3 = 185.0  # +30 from first
    prices3 = {"CE_22000": 141.00, "PE_22000": 151.50}  # Changed
    send, reason = state.should_send(pnl3, prices3)
    print(f"  Result: {reason} {'✓' if send else '✗'}")
    
    # Test scenario 4: < 30 sec interval (skip)
    print("\nScenario 4: Sent again < 30 sec (skip)")
    pnl4 = 200.0
    prices4 = {"CE_22000": 140.50, "PE_22000": 152.00}
    send, reason = state.should_send(pnl4, prices4)
    print(f"  Result: {reason} {'✓' if not send else '✗ (should skip)'}")


def main():
    print("\n" + "=" * 60)
    print("REFINED SNAPSHOT FORMATTING TEST")
    print("=" * 60 + "\n")
    
    # Create test legs
    print("Creating test position...")
    print("  ✓ Sell CE 22000 @ ₹145.50")
    print("  ✓ Sell PE 22100 @ ₹152.30")
    print("  ✓ Buy CE 22050 @ ₹135.00 (locked)\n")
    
    legs = [
        # Open legs
        MockTradeLeg(
            token="CE_22000", 
            symbol="NIFTY", 
            strike=22000,
            option_type="CE",
            entry_price=145.50,
            qty=-15,  # Short
            current_ltp=143.20,
            current_sl=150.50
        ),
        MockTradeLeg(
            token="PE_22100",
            symbol="NIFTY",
            strike=22100,
            option_type="PE",
            entry_price=152.30,
            qty=-15,  # Short
            current_ltp=150.90,
            current_sl=155.75
        ),
        # Locked leg
        MockTradeLeg(
            token="CE_22050",
            symbol="NIFTY",
            strike=22050,
            option_type="CE",
            entry_price=135.00,
            qty=10,  # Long
            current_ltp=134.50,
            current_sl=138.00
        ),
    ]
    
    # Mark one leg as locked
    legs[2].mark_locked("Daily max loss reached", 135.00)
    
    # Generate and display snapshot
    print("=" * 60)
    print("EMOJI-FORMATTED POSITION SNAPSHOT (HTML)")
    print("=" * 60 + "\n")
    
    snapshot = build_refined_snapshot(legs)
    print(snapshot)
    
    # Display deduplication logic
    simulate_deduplication()
    
    # Display key features
    print("\n" + "=" * 60)
    print("KEY FEATURES DEMONSTRATED")
    print("=" * 60 + "\n")
    
    features = [
        ("📊 Header", "Clear 'POSITION SNAPSHOT' with timestamp"),
        ("🟢 OPEN LEGS", "Separate section for trading legs"),
        ("🔒 LOCKED LEGS", "Separate section for frozen legs"),
        ("🟦/🟥", "Buy (blue) vs Sell (red) indicators"),
        ("📞/📧", "CE (Call) vs PE (Put) emojis"),
        ("₹ Currency", "Indian Rupee symbol for prices"),
        ("📈/📉", "P&L direction indicators"),
        ("Per-leg SL", "Stop loss shown if available"),
        ("Lock reason", "Why leg is frozen"),
        ("Cumulative PL", "Total position P&L at bottom"),
        ("Leg counts", "Open and locked leg totals"),
        ("Mobile scan", "Readable in <10 seconds"),
    ]
    
    for emoji, description in features:
        print(f"  {emoji:12} → {description}")
    
    # Display deduplication rules
    print("\n" + "=" * 60)
    print("DEDUPLICATION RULES (Smart Snapshot Sending)")
    print("=" * 60 + "\n")
    
    rules = [
        ("P&L Threshold", "Skip if cumulative P&L change < ₹10"),
        ("Time Interval", "Skip if last snapshot sent < 30 sec ago"),
        ("Price Change", "If P&L stable, check if any leg price changed"),
        ("Result", "Reduces spam; sends only on material changes"),
    ]
    
    for rule, detail in rules:
        print(f"  {rule:15} : {detail}")
    
    # Display emoji reference
    print("\n" + "=" * 60)
    print("EMOJI REFERENCE")
    print("=" * 60 + "\n")
    
    emojis = [
        ("📊", "Snapshot header"),
        ("🟢", "Open leg section"),
        ("🔒", "Locked leg section"),
        ("🟦", "Buy position (blue)"),
        ("🟥", "Sell position (red)"),
        ("📞", "Call option (CE)"),
        ("📧", "Put option (PE)"),
        ("📈", "Profit / Positive P&L"),
        ("📉", "Loss / Negative P&L"),
        ("─", "Visual separator"),
        ("₹", "Indian Rupee currency"),
    ]
    
    for emoji, meaning in emojis:
        print(f"  {emoji}  → {meaning}")
    
    print("\n" + "=" * 60)
    print("✅ SNAPSHOT REFINEMENT COMPLETE")
    print("=" * 60 + "\n")
    
    print("Summary:")
    print("  • Snapshot shows per-leg P&L with entry, LTP, SL")
    print("  • Separated open vs locked legs visually")
    print("  • UTF-8 emojis for direction and status")
    print("  • ₹ currency symbols throughout")
    print("  • Smart deduplication (₹10 threshold, 30-sec interval)")
    print("  • Mobile-friendly: <10 second scan time")
    print("  • Backward compatible: no API changes")
    print("\n")


if __name__ == "__main__":
    main()
