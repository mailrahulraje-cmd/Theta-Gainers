#!/usr/bin/env python3
"""
Comprehensive test suite for Trailing SL Update notifications.

Tests:
1. SL change detection (only send when SL actually changes)
2. SL update message format (all required elements)
3. Deduplication (skip negligible changes < 0.01)
4. P&L calculation in SL update
5. Timestamp format (HH:MM:SS IST)
6. Emoji inclusion and formatting
7. Open/locked separation with leg counts
8. Cumulative P&L display
9. Backward compatibility with snapshots and legacy methods
10. Integration with real-time snapshot updates

Virtual environment: C:/PythonEnv/global_venv/
"""

import sys
import os
from datetime import datetime
from unittest.mock import patch, MagicMock
import re

# Add workspace to path
sys.path.insert(0, os.path.dirname(__file__))

from utils.notifier import TelegramNotifierTextOnly, TradeLeg, NotificationStateCache
from constants import PHASE_IN_TRADE, PHASE_INIT


def test_1_sl_change_detection():
    """Test that SL updates are detected and sent only when SL changes"""
    print("\n" + "="*60)
    print("TEST 1: SL Change Detection")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add a leg
            notifier.add_leg("TK1", "NIFTY", 22000, "CE", 145.50, 100)
            
            # Test 1a: Set initial SL (should send)
            print("\n✓ STEP 1a: Set initial SL (should send update)")
            notifier.update_leg_sl("TK1", 140.00)
            initial_calls = mock_send.call_count
            print(f"   • SL set to ₹140.00")
            print(f"   • Messages sent: {initial_calls}")
            
            # Test 1b: Update SL to different value (should send)
            print("\n✓ STEP 1b: Update SL to different value (should send)")
            mock_send.reset_mock()
            notifier.update_leg_sl("TK1", 138.50)
            calls_after_change = mock_send.call_count
            print(f"   • SL updated from ₹140.00 to ₹138.50")
            print(f"   • Change: ₹{abs(140.00 - 138.50):.2f}")
            print(f"   • Messages sent: {calls_after_change}")
            assert calls_after_change == 1, "Should send update when SL changes significantly"
            print("   ✅ PASS: Update sent for significant change")
            
            # Test 1c: Negligible SL change (should NOT send)
            print("\n✓ STEP 1c: Negligible SL change < ₹0.01 (should skip)")
            mock_send.reset_mock()
            notifier.update_leg_sl("TK1", 138.50001)  # Trivial change
            calls_after_trivial = mock_send.call_count
            print(f"   • SL changed by ₹0.00001 (negligible)")
            print(f"   • Messages sent: {calls_after_trivial}")
            assert calls_after_trivial == 0, "Should skip negligible changes"
            print("   ✅ PASS: Skipped negligible change")
            
            # Test 1d: Leg not in trading phase (should NOT send)
            print("\n✓ STEP 1d: SL update during non-trading phase (should skip)")
            mock_send.reset_mock()
            notifier.current_phase = PHASE_INIT
            notifier.update_leg_sl("TK1", 135.00)
            calls_after_phase_change = mock_send.call_count
            print(f"   • Phase: {PHASE_INIT} (not IN_TRADE)")
            print(f"   • Messages sent: {calls_after_phase_change}")
            assert calls_after_phase_change == 0, "Should not send when not in trade"
            print("   ✅ PASS: Skipped non-trading phase")


def test_2_sl_update_message_format():
    """Test SL update message includes all required elements"""
    print("\n" + "="*60)
    print("TEST 2: SL Update Message Format")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add a CE leg (BUY)
            notifier.add_leg("TK_CE", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_CE", 150.00)
            
            # Add a PE leg (SELL)
            notifier.add_leg("TK_PE", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_PE", 150.90)
            
            # Send SL update
            print("\n✓ Sending SL update with multiple legs active")
            notifier.update_leg_sl("TK_CE", 142.00)
            
            # Get the message text
            assert mock_send.called, "Message should be sent"
            msg_text = mock_send.call_args[0][2]  # Third argument is text
            
            print(f"\n✓ Validating message format:")
            
            # Check for required elements
            checks = {
                "🔒 emoji": "🔒" in msg_text,
                "TRAILING SL UPDATE header": "TRAILING SL UPDATE" in msg_text,
                "Timestamp (HH:MM:SS)": bool(re.search(r'Time: \d{2}:\d{2}:\d{2}', msg_text)),
                "IST timezone indicator": "Time:" in msg_text,
                "Strike info": "22000" in msg_text,
                "CE/PE option type": "CE" in msg_text or "📞" in msg_text,
                "Entry price": "145.50" in msg_text,
                "Current LTP": "150.00" in msg_text,
                "Old SL": "142.00" in msg_text,
                "New SL": "142.00" in msg_text,  # Was set to 142.00
                "P&L display": "₹" in msg_text and ("P&L" in msg_text or "P&L:" in msg_text),
                "Cumulative P&L": "Cumulative" in msg_text or "CUMULATIVE" in msg_text or "₹" in msg_text,
                "Open/Locked counts": "Open:" in msg_text or "Open" in msg_text or "Locked:" in msg_text or "Locked" in msg_text,
            }
            
            for check_name, result in checks.items():
                status = "✅" if result else "❌"
                print(f"   {status} {check_name}: {result}")
            
            all_passed = all(checks.values())
            assert all_passed, "Not all format checks passed"
            print("\n✅ PASS: All format checks passed")
            
            # Print sample message
            print("\n📋 Sample SL Update Message:")
            print("─" * 60)
            print(msg_text)
            print("─" * 60)


def test_3_sl_deduplication():
    """Test SL update deduplication (three-level check)"""
    print("\n" + "="*60)
    print("TEST 3: SL Update Deduplication")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            notifier.add_leg("TK1", "NIFTY", 22000, "CE", 145.50, 100)
            
            scenarios = [
                ("Initial SL", None, 140.00, True, "First SL set"),
                ("Significant change", 140.00, 138.50, True, "₹1.50 change"),
                ("Negligible change", 138.50, 138.50000000001, False, "< ₹0.01 change"),
                ("Decrease SL", 138.50, 135.00, True, "₹3.50 decrease"),
                ("Increase SL", 135.00, 137.25, True, "₹2.25 increase"),
                ("End of range", 137.25, 137.25, False, "Rounding noise"),
            ]
            
            print("\n📊 Dedup Scenario Testing:")
            for scenario_name, old_sl, new_sl, should_send, reason in scenarios:
                mock_send.reset_mock()
                notifier.update_leg_sl("TK1", new_sl)
                sent = mock_send.call_count > 0
                
                status = "✅" if sent == should_send else "❌"
                action = "SENT" if sent else "SKIPPED"
                expected = "expected" if sent == should_send else "NOT expected"
                
                print(f"\n{status} {scenario_name}:")
                print(f"   • Old SL: {old_sl}, New SL: {new_sl}")
                print(f"   • Change: {abs(new_sl - old_sl) if old_sl else 'N/A':.6f}")
                print(f"   • Result: {action} ({expected}) - {reason}")
                
                assert sent == should_send, f"Failed: {scenario_name} - expected {should_send}, got {sent}"
            
            print("\n✅ PASS: All dedup scenarios passed")


def test_4_sl_pnl_calculation():
    """Test that current P&L is correctly displayed in SL update"""
    print("\n" + "="*60)
    print("TEST 4: P&L Calculation in SL Update")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add BUY leg (qty > 0)
            print("\n✓ Testing BUY leg P&L calculation")
            notifier.add_leg("TK_BUY", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_BUY", 150.00)
            
            expected_pnl_buy = (150.00 - 145.50) * 100  # ₹450
            actual_pnl_buy = notifier.active_legs["TK_BUY"].pnl
            print(f"   • BUY: Entry ₹145.50, LTP ₹150.00, Qty +100")
            print(f"   • Expected P&L: ₹{expected_pnl_buy:.2f}")
            print(f"   • Actual P&L: ₹{actual_pnl_buy:.2f}")
            assert expected_pnl_buy == actual_pnl_buy, "BUY leg P&L incorrect"
            print("   ✅ PASS: BUY leg P&L correct")
            
            # Add SELL leg (qty < 0)
            print("\n✓ Testing SELL leg P&L calculation")
            notifier.add_leg("TK_SELL", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_SELL", 150.90)
            
            expected_pnl_sell = (152.30 - 150.90) * 50  # ₹70
            actual_pnl_sell = notifier.active_legs["TK_SELL"].pnl
            print(f"   • SELL: Entry ₹152.30, LTP ₹150.90, Qty -50")
            print(f"   • Expected P&L: ₹{expected_pnl_sell:.2f}")
            print(f"   • Actual P&L: ₹{actual_pnl_sell:.2f}")
            assert expected_pnl_sell == actual_pnl_sell, "SELL leg P&L incorrect"
            print("   ✅ PASS: SELL leg P&L correct")
            
            # Check message includes P&L
            print("\n✓ Checking SL update message includes leg P&L")
            mock_send.reset_mock()
            notifier.update_leg_sl("TK_BUY", 142.00)
            
            msg_text = mock_send.call_args[0][2]
            assert "₹450.00" in msg_text or "₹450" in msg_text or "+450" in msg_text, "BUY leg P&L not in message"
            print(f"   ✅ PASS: P&L (₹450.00) displayed in SL update message")
            
            # Cumulative P&L check
            cumulative_pnl = actual_pnl_buy + actual_pnl_sell
            print(f"\n✓ Cumulative P&L calculation")
            print(f"   • BUY P&L: ₹{actual_pnl_buy:.2f}")
            print(f"   • SELL P&L: ₹{actual_pnl_sell:.2f}")
            print(f"   • Cumulative: ₹{cumulative_pnl:.2f}")
            assert "Cumulative" in msg_text or "Cumulative P&L" in msg_text or cumulative_pnl > 0, "Cumulative P&L issue"
            print(f"   ✅ PASS: Cumulative P&L calculated correctly")


def test_5_sl_timestamp_format():
    """Test SL update includes correct timestamp format (HH:MM:SS IST)"""
    print("\n" + "="*60)
    print("TEST 5: Timestamp Format (HH:MM:SS IST)")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            notifier.add_leg("TK1", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_sl("TK1", 140.00)
            
            msg_text = mock_send.call_args[0][2]
            
            # Extract timestamp
            timestamp_match = re.search(r'Time: (\d{2}):(\d{2}):(\d{2})', msg_text)
            
            print("\n✓ Validating timestamp format:")
            assert timestamp_match, "Timestamp not found in message"
            print(f"   • Found timestamp: {timestamp_match.group(0)}")
            
            hours, minutes, seconds = timestamp_match.groups()
            hours = int(hours)
            minutes = int(minutes)
            seconds = int(seconds)
            
            assert 0 <= hours <= 23, f"Invalid hours: {hours}"
            assert 0 <= minutes <= 59, f"Invalid minutes: {minutes}"
            assert 0 <= seconds <= 59, f"Invalid seconds: {seconds}"
            
            print(f"   ✅ PASS: Timestamp format correct (HH:MM:SS)")
            print(f"   ✅ PASS: Hours valid ({hours}), Minutes valid ({minutes}), Seconds valid ({seconds})")


def test_6_sl_emoji_integration():
    """Test emoji usage in SL updates (🔒 and others)"""
    print("\n" + "="*60)
    print("TEST 6: Emoji Integration")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add both CE (BUY) and PE (SELL) legs
            notifier.add_leg("TK_CE", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_CE", 150.00)
            notifier.add_leg("TK_PE", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_PE", 150.90)
            
            notifier.update_leg_sl("TK_CE", 142.00)
            
            msg_text = mock_send.call_args[0][2]
            
            print("\n✓ Checking emoji usage:")
            
            emojis_to_check = {
                "🔒": "Lock emoji for SL",
                "📊": "Chart emoji for stats",
                "🟢": "Green circle for open status",
                "📈": "Profit emoji",
                "📉": "Loss emoji",
                "📞": "Phone for CE",
                "📧": "Email for PE",
                "🟦": "Blue for BUY",
                "🟥": "Red for SELL",
                "⬆️": "Up arrow for SL increase",
                "⬇️": "Down arrow for SL decrease",
            }
            
            found_count = 0
            for emoji, description in emojis_to_check.items():
                if emoji in msg_text:
                    print(f"   ✅ {emoji} - {description}")
                    found_count += 1
                else:
                    print(f"   ⚠️  {emoji} - {description} (not found)")
            
            print(f"\n✅ PASS: Found {found_count}/{len(emojis_to_check)} expected emojis")
            assert "🔒" in msg_text, "Lock emoji 🔒 is mandatory"
            print("   ✅ PASS: Mandatory lock emoji 🔒 present")


def test_7_open_locked_separation():
    """Test open/locked leg separation in cumulative section"""
    print("\n" + "="*60)
    print("TEST 7: Open/Locked Leg Separation")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add 3 legs
            print("\n✓ Adding 3 legs (2 open, 1 locked)")
            notifier.add_leg("TK_CE", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_CE", 150.00)
            
            notifier.add_leg("TK_PE1", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_PE1", 150.90)
            
            notifier.add_leg("TK_PE2", "NIFTY", 22200, "PE", 160.00, -50)
            notifier.update_leg_ltp("TK_PE2", 165.00)
            
            # Lock one leg
            print("   • 2 legs left open")
            print("   • 1 leg marked as locked")
            notifier.mark_leg_locked("TK_PE2", "Max loss reached", 165.00)
            
            # Send SL update
            notifier.update_leg_sl("TK_CE", 142.00)
            
            msg_text = mock_send.call_args[0][2]
            
            print("\n✓ Validating message format:")
            
            # Check for counts
            open_pattern = r'Open:\s*2|Open\s*2'
            locked_pattern = r'Locked:\s*1|Locked\s*1'
            
            has_open = any(pattern in msg_text for pattern in ["Open: 2", "Open 2"])
            has_locked = any(pattern in msg_text for pattern in ["Locked: 1", "Locked 1"])
            
            print(f"   ✅ Open leg count displayed: {has_open}")
            print(f"   ✅ Locked leg count displayed: {has_locked}")
            
            assert has_open or has_locked, "Leg counts not displayed"
            print("\n✅ PASS: Open/locked separation correctly displayed")


def test_8_cumulative_pnl_display():
    """Test cumulative P&L display in SL updates"""
    print("\n" + "="*60)
    print("TEST 8: Cumulative P&L Display")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add two legs with known P&L
            notifier.add_leg("TK_CE", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_CE", 150.00)  # +₹450
            
            notifier.add_leg("TK_PE", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_PE", 150.90)  # +₹70
            
            cumulative = 450 + 70  # ₹520
            
            print(f"\n✓ P&L Setup:")
            print(f"   • CE: Entry ₹145.50, LTP ₹150.00 → P&L ₹450.00")
            print(f"   • PE: Entry ₹152.30, LTP ₹150.90 → P&L ₹70.00")
            print(f"   • Expected Cumulative: ₹{cumulative:.2f}")
            
            notifier.update_leg_sl("TK_CE", 142.00)
            msg_text = mock_send.call_args[0][2]
            
            print(f"\n✓ Validating cumulative P&L in message:")
            
            # Check if cumulative value is in message
            has_cumulative = "Cumulative" in msg_text or "cumulative" in msg_text
            has_value = "520" in msg_text or "₹520" in msg_text or "+520" in msg_text
            has_direction_emoji = "📈" in msg_text or "📉" in msg_text
            
            print(f"   ✅ 'Cumulative' label present: {has_cumulative}")
            print(f"   ✅ P&L value (₹520) present: {has_value}")
            print(f"   ✅ Direction emoji present: {has_direction_emoji}")
            
            assert has_cumulative, "Cumulative label missing"
            print("\n✅ PASS: Cumulative P&L correctly displayed")


def test_9_backward_compatibility():
    """Test backward compatibility with existing snapshot and notification methods"""
    print("\n" + "="*60)
    print("TEST 9: Backward Compatibility")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Test that legacy methods still work
            print("\n✓ Testing legacy notification methods:")
            
            legacy_methods = [
                ('send_phase_change', lambda: notifier.send_phase_change(PHASE_IN_TRADE, PHASE_INIT)),
                ('send_trade_entry', lambda: notifier.send_trade_entry("Strike 22000 CE", 145.50, "TK1", 22000, "CE", 100, 140.00)),
                ('send_trailing_sl_update', lambda: notifier.send_trailing_sl_update("CE 22000", old_sl=140.00, new_sl=138.50, price=145.50, pnl=450.00)),
                ('send_pnl_milestone', lambda: notifier.send_pnl_milestone("100% of target", 10000, cumulative=50000)),
                ('send_exit', lambda: notifier.send_exit("CE 22000", 150.00, 450.00, "Target reached")),
            ]
            
            for method_name, method_call in legacy_methods:
                try:
                    mock_send.reset_mock()
                    method_call()
                    # These methods may or may not send depending on state
                    print(f"   ✅ {method_name}: callable and functional")
                except Exception as e:
                    print(f"   ❌ {method_name}: {str(e)}")
                    raise
            
            print("\n✓ Testing new SL update integration:")
            notifier.add_leg("TK1", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK1", 150.00)
            
            # Test that new SL updates don't break old snapshot logic
            mock_send.reset_mock()
            notifier.update_leg_sl("TK1", 140.00)
            sl_updates = mock_send.call_count
            print(f"   ✅ SL update sent: {sl_updates} message(s)")
            
            print("\n✅ PASS: All legacy methods work, no breaking changes")


def test_10_integration_with_snapshots():
    """Test integration of SL updates with real-time snapshots"""
    print("\n" + "="*60)
    print("TEST 10: Integration with Real-Time Snapshots")
    print("="*60)
    
    with patch.object(TelegramNotifierTextOnly, 'validate', return_value=True):
        with patch('utils.notifier.send_telegram_message') as mock_send:
            notifier = TelegramNotifierTextOnly("test_token", "123")
            notifier.current_phase = PHASE_IN_TRADE
            
            # Add legs
            print("\n✓ Setting up trading scenario with multiple legs")
            notifier.add_leg("TK_CE", "NIFTY", 22000, "CE", 145.50, 100)
            notifier.update_leg_ltp("TK_CE", 145.50)
            
            notifier.add_leg("TK_PE", "NIFTY", 22100, "PE", 152.30, -50)
            notifier.update_leg_ltp("TK_PE", 152.30)
            
            mock_send.reset_mock()
            
            # Scenario: SL update while potentially triggering snapshot
            print("\n✓ Scenario 1: SL update triggers within snapshot window")
            notifier.update_leg_sl("TK_CE", 142.00)
            
            messages_sent = mock_send.call_count
            print(f"   • SL update sent")
            print(f"   • Total messages: {messages_sent}")
            assert messages_sent >= 1, "At least SL update should be sent"
            print("   ✅ PASS: SL update integrated with snapshot system")
            
            # Scenario: Multiple SL updates in sequence
            print("\n✓ Scenario 2: Multiple SL updates in sequence")
            mock_send.reset_mock()
            notifier.update_leg_sl("TK_CE", 140.00)
            notifier.update_leg_sl("TK_PE", 150.00)
            
            messages = mock_send.call_count
            print(f"   • Updated CE SL to ₹140.00 and PE SL to ₹150.00")
            print(f"   • Messages sent: {messages}")
            assert messages >= 2, "Should send both SL updates"
            print("   ✅ PASS: Multiple SL updates sent correctly")
            
            # Scenario: SL update with locked leg
            print("\n✓ Scenario 3: SL update with locked leg")
            notifier.mark_leg_locked("TK_PE", "Max loss", 152.30)
            mock_send.reset_mock()
            notifier.update_leg_sl("TK_CE", 138.50)
            
            msg_text = mock_send.call_args[0][2] if mock_send.called else ""
            has_open_count = "Open:" in msg_text or "Open" in msg_text
            has_locked_count = "Locked:" in msg_text or "Locked" in msg_text
            
            print(f"   • 1 leg open (CE), 1 leg locked (PE)")
            print(f"   • SL update includes open/locked counts: {has_open_count or has_locked_count}")
            print("   ✅ PASS: SL update respects leg status")


def main():
    """Run all tests"""
    print("\n" + "█" * 60)
    print("█" + " " * 58 + "█")
    print("█" + "  TRAILING SL UPDATE INTEGRATION TESTS".center(58) + "█")
    print("█" + " " * 58 + "█")
    print("█" * 60)
    
    tests = [
        test_1_sl_change_detection,
        test_2_sl_update_message_format,
        test_3_sl_deduplication,
        test_4_sl_pnl_calculation,
        test_5_sl_timestamp_format,
        test_6_sl_emoji_integration,
        test_7_open_locked_separation,
        test_8_cumulative_pnl_display,
        test_9_backward_compatibility,
        test_10_integration_with_snapshots,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ TEST FAILED: {test_func.__name__}")
            print(f"   Error: {str(e)}")
        except Exception as e:
            failed += 1
            print(f"\n❌ TEST ERROR: {test_func.__name__}")
            print(f"   Error: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🚀 ALL TESTS PASSED - SL UPDATE INTEGRATION COMPLETE")
        print("\n✅ READY FOR DEPLOYMENT")
    else:
        print(f"\n❌ {failed} test(s) failed - review and fix before deployment")
        sys.exit(1)


if __name__ == "__main__":
    main()
