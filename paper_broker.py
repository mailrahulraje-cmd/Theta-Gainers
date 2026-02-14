import threading
import uuid
import csv
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import Config
from utils.logger import logger, trade_logger
from contract import BrokerProtocol, OrderDict, FeedProtocol
from core.execution_gateway import get_execution_gateway

def ist_now() -> datetime:
    return datetime.now(Config.TZ)

class PaperBroker:
    def __init__(self, state, trades_csv: str = "trades.csv", notifier: Optional[Any] = None, lots: int = 1):
        """
        state: StrategyState-like object with get/set/update methods
        notifier: optional Telegram notifier instance (send_entry/send_exit/send_trade_log)
        trades_csv: path to append trade records
        lots: default lot multiplier (Config.LOTS)
        """
        self.state = state
        self.notifier = notifier
        self.lots = int(lots)
        self.positions: Dict[str, Dict[str, Any]] = {}  # token -> {'qty': int, 'avg_price': float, 'side': 'LONG'/'SHORT' or None, 'last_price': float}
        self.orders: List[Dict[str, Any]] = []
        self.order_lock = threading.Lock()
        self.trades_csv = trades_csv
        self._init_csv()
        self._restore_positions()
        self.net_realized = 0.0
        
        # CRITICAL: Initialize execution gateway for safety enforcement
        self.gateway = get_execution_gateway()
        logger.info(" PaperBroker: ExecutionGateway integrated")

    # -------------------------
    # persistence
    # -------------------------
    def _init_csv(self):
        try:
            if not os.path.exists(self.trades_csv):
                with open(self.trades_csv, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(['timestamp', 'order_id', 'side', 'token', 'qty', 'price', 'tag', 'status'])
        except Exception:
            logger.exception("Failed to init trades csv")

    def _restore_positions(self):
        try:
            saved = self.state.get('broker_positions')
            if saved:
                self.positions = saved
                logger.info(f" Restored {len(saved)} positions")
                for token, pos in saved.items():
                    if pos.get('qty', 0) != 0:
                        logger.info(f"    {token}: {pos.get('side')} {abs(pos.get('qty'))} @ {pos.get('avg_price',0.0):.2f}")
        except Exception:
            logger.exception("Failed to restore positions from state")

    def _save_positions(self):
        try:
            self.state.set('broker_positions', self.positions)
        except Exception:
            logger.exception("Failed to save broker positions to state")

    # -------------------------
    # order API (flexible)
    # -------------------------
    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Flexible wrapper to support multiple call signatures used across code:
        - place_order(side, token, qty, price, tag="")
        - place_order(token, symbol, side, price, qty, meta)
        - place_order(token, symbol, side, price, qty)
        - place_order(side=..., token=..., qty=..., price=..., meta=...)
        Returns an order dict (status FILLED).
        if Config.DEBUG_MODE:
            logger.debug(f"[PAPER_BROKER] place_order called with args={args}, kwargs={kwargs}")
        
        """
        # Normalize parameters
        side = None
        token = None
        qty = None
        price = None
        tag = ""
        meta = {}

        # positional parsing
        try:
            if len(args) == 4 or len(args) == 5:
                # (side, token, qty, price, [tag])
                side = args[0]
                token = args[1]
                qty = int(args[2])
                price = float(args[3])
                if len(args) == 5:
                    tag = args[4]
            elif len(args) >= 5:
                # (token, symbol, side, price, qty, [meta])
                token = args[0]
                # symbol = args[1]  # not used here
                side = args[2]
                price = float(args[3])
                qty = int(args[4])
                if len(args) >= 6:
                    meta = args[5] or {}
                    tag = meta.get('label', tag)
            # kwargs override
            side = kwargs.get('side', side)
            token = kwargs.get('token', token)
            qty = int(kwargs.get('qty', qty or 0))
            price = float(kwargs.get('price', price or 0.0))
            tag = kwargs.get('tag', kwargs.get('label', tag))
            meta = kwargs.get('meta', meta)
        except Exception:
            logger.exception("Invalid place_order signature")
            raise

        # apply lot multiplier if qty is in lots
        if qty is None:
            qty = 1
        try:
            qty = int(qty)
        except Exception:
            qty = 1
        
        # ================================================================
        # CRITICAL: EXECUTION GATEWAY VALIDATION
        # ================================================================
        # Validate order through execution gateway BEFORE placing
        symbol = kwargs.get('symbol', f"Token-{token}")
        allowed, reason = self.gateway.validate_order(
            symbol=symbol,
            transaction_type=str(side).upper() if side else 'BUY',
            quantity=qty,
            price=price,
            order_type='MARKET'
        )
        
        if not allowed:
            logger.error(f" Order REJECTED by ExecutionGateway: {reason}")
            return {
                'order_id': None,
                'status': 'REJECTED',
                'message': reason,
                'side': str(side).upper() if side else 'BUY',
                'token': str(token),
                'qty': qty,
                'price': price,
                'timestamp': ist_now().isoformat()
            }
        # ================================================================

        order = {
            'order_id': str(uuid.uuid4()),
            'side': str(side).upper() if side else 'BUY',
            'token': str(token),
            'qty': qty,
            'price': float(price),
            'tag': tag or meta.get('label', ''),
            'meta': meta,
            'timestamp': ist_now().isoformat(),
            'status': 'FILLED'
        }

        logger.info(f"[PAPER_BROKER] Executing order: {order['order_id']} | {order['side']} {order['qty']} @ {order['price']:.2f} | {order['tag']}")
        
        with self.order_lock:
            try:
                self.orders.append(order)
                # apply fill immediately
                self._apply_fill(order)
                logger.info(f"[PAPER_BROKER]  Order FILLED: {order['order_id']} | Status: {order['status']}")
                # log
                trade_logger.info(f"{order['side']} {order['qty']} @ {order['price']:.2f} | {order['tag']}")
                # append to CSV
                try:
                    with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
                        csv.writer(f).writerow([order['timestamp'], order['order_id'], order['side'], order['token'], order['qty'], f"{order['price']:.2f}", order['tag'], order['status']])
                except Exception:
                    logger.exception("Failed to write trade to CSV")
                # save positions to state
                self._save_positions()
                # notifier hooks (non-blocking)
                if self.notifier:
                    try:
                        label = order['tag'] or f"{order['side']} {order['token']}"
                        if order['side'] == "SELL":
                            # treat SELL as entry for short
                            threading.Thread(target=self.notifier.send_entry, args=(f" {label}", order['price']), daemon=True).start()
                        elif order['side'] == "BUY":
                            threading.Thread(target=self.notifier.send_entry, args=(f" {label}", order['price']), daemon=True).start()
                        # always send trade log
                        threading.Thread(target=self.notifier.send_trade_log, args=(f"{order['side']} {order['token']} @ {order['price']:.2f} | {order['tag']}",), daemon=True).start()
                    except Exception:
                        logger.exception("Notifier hook failed in place_order")
            except Exception:
                logger.exception("place_order failed")
                raise
        return order

    # -------------------------
    # internal fill application
    # -------------------------
    def _apply_fill(self, order: Dict[str, Any]):
        """
        Update positions dict based on immediate fill semantics.
        Positions stored as: {'qty': int, 'avg_price': float, 'side': 'LONG'/'SHORT'/None, 'last_price': float}
        Positive qty -> LONG, Negative qty -> SHORT
        """
        token = str(order['token'])
        side = order['side'].upper()
        qty = int(order['qty'])
        price = float(order['price'])

        pos = self.positions.get(token)
        if pos is None:
            pos = {'qty': 0, 'avg_price': 0.0, 'side': None, 'last_price': price}
            self.positions[token] = pos

        # normalize: BUY increases qty, SELL decreases qty
        if side == "BUY":
            # if existing short, reduce/close short first
            if pos['qty'] < 0:
                # closing short
                close_qty = min(qty, abs(pos['qty']))
                realized = (pos['avg_price'] - price) * close_qty
                self.net_realized += realized
                pos['qty'] += close_qty  # less negative
                pos['last_price'] = price
                qty -= close_qty
                if pos['qty'] == 0:
                    pos['avg_price'] = 0.0
                    pos['side'] = None
                # if remaining qty opens long
                if qty > 0:
                    total_val = (0 * 0.0) + (qty * price)
                    pos['qty'] += qty
                    pos['avg_price'] = (total_val / pos['qty']) if pos['qty'] != 0 else 0.0
                    pos['side'] = 'LONG'
                    pos['last_price'] = price
            else:
                # adding to long
                total_val = (pos['qty'] * pos['avg_price']) + (qty * price)
                pos['qty'] += qty
                pos['avg_price'] = (total_val / pos['qty']) if pos['qty'] != 0 else 0.0
                pos['side'] = 'LONG'
                pos['last_price'] = price
        else:  # SELL
            if pos['qty'] > 0:
                # closing long
                close_qty = min(qty, pos['qty'])
                realized = (price - pos['avg_price']) * close_qty
                self.net_realized += realized
                pos['qty'] -= close_qty
                pos['last_price'] = price
                qty -= close_qty
                if pos['qty'] == 0:
                    pos['avg_price'] = 0.0
                    pos['side'] = None
                # remaining qty opens short
                if qty > 0:
                    total_val = (abs(pos['qty']) * pos['avg_price']) + (qty * price)
                    # pos['qty'] becomes negative
                    pos['qty'] -= qty
                    pos['avg_price'] = (total_val / abs(pos['qty'])) if pos['qty'] != 0 else 0.0
                    pos['side'] = 'SHORT'
                    pos['last_price'] = price
            else:
                # adding to short
                total_val = (abs(pos['qty']) * pos['avg_price']) + (qty * price)
                pos['qty'] -= qty
                pos['avg_price'] = (total_val / abs(pos['qty'])) if pos['qty'] != 0 else 0.0
                pos['side'] = 'SHORT'
                pos['last_price'] = price

        # cleanup zero positions
        if pos['qty'] == 0:
            pos['side'] = None
            pos['avg_price'] = 0.0
            pos['last_price'] = price

        # persist positions in state
        try:
            self.state.set('broker_positions', self.positions)
        except Exception:
            logger.exception("Failed to persist positions after fill")

        # If this fill closed a position, send exit notification with realized pnl if available
        try:
            if self.notifier:
                # If order tag indicates an exit, attempt to notify
                tag = order.get('tag', '') or order.get('meta', {}).get('label', '')
                if tag and any(k in str(tag).upper() for k in ("EXIT", "CLOSE", "SQUAREOFF")):
                    # best-effort realized pnl: use net_realized
                    threading.Thread(target=self.notifier.send_exit, args=(f" {tag}", price, self.net_realized, tag), daemon=True).start()
        except Exception:
            logger.exception("Notifier send_exit failed in _apply_fill")

    # -------------------------
    # query API
    # -------------------------
    def get_positions(self) -> List[Dict[str, Any]]:
        """Return list of position dicts"""
        with self.order_lock:
            return [{ 'token': t, **v } for t, v in self.positions.items()]

    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Return dict token -> position for non-zero qty"""
        with self.order_lock:
            return {k: v for k, v in self.positions.items() if v.get('qty', 0) != 0}

    def get_position_count(self) -> int:
        with self.order_lock:
            return sum(abs(v.get('qty', 0)) for v in self.positions.values())

    def get_total_pnl(self, feed: FeedProtocol) -> float:
        """
        Compute net P&L = realized (net_realized) + unrealized based on feed.get_ltp(token)
        feed: UnifiedFeed-like with get_ltp(token, check_freshness=False)
        """
        unreal = 0.0
        with self.order_lock:
            for token, pos in self.positions.items():
                qty = pos.get('qty', 0)
                if qty == 0:
                    continue
                ltp = None
                try:
                    ltp = feed.get_ltp(token, check_freshness=False)
                except Exception:
                    try:
                        ltp = feed.get_ltp(token)
                    except Exception:
                        ltp = None
                if ltp is None:
                    ltp = pos.get('last_price', pos.get('avg_price', 0.0))
                if qty > 0:
                    unreal += (ltp - pos.get('avg_price', 0.0)) * qty
                else:
                    unreal += (pos.get('avg_price', 0.0) - ltp) * abs(qty)
        return self.net_realized + unreal

    # -------------------------
    # utility: close all positions at provided market prices
    # -------------------------
    def close_all(self, market_prices: Dict[str, float]):
        """
        Force-close all positions at provided market_prices (token -> ltp).
        Sends exit notifications for each closed position.
        """
        with self.order_lock:
            tokens = list(self.positions.keys())
        for token in tokens:
            with self.order_lock:
                pos = self.positions.get(token)
                if not pos or pos.get('qty', 0) == 0:
                    continue
                qty = abs(pos['qty'])
                side = "BUY" if pos['qty'] < 0 else "SELL"
                ltp = market_prices.get(str(token), pos.get('last_price', pos.get('avg_price', 0.0)))
            try:
                # create a synthetic order to close
                order = {
                    'order_id': str(uuid.uuid4()),
                    'side': side,
                    'token': token,
                    'qty': qty,
                    'price': float(ltp),
                    'tag': "SQUAREOFF",
                    'timestamp': ist_now().isoformat(),
                    'status': 'FILLED'
                }
                with self.order_lock:
                    self.orders.append(order)
                    self._apply_fill(order)
                    trade_logger.info(f"{order['side']} {order['qty']} @ {order['price']:.2f} | {order['tag']}")
                    try:
                        with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([order['timestamp'], order['order_id'], order['side'], order['token'], order['qty'], f"{order['price']:.2f}", order['tag'], order['status']])
                    except Exception:
                        logger.exception("Failed to write squareoff to CSV")
                    # notifier exit
                    if self.notifier:
                        try:
                            threading.Thread(target=self.notifier.send_exit, args=(f" {order['tag']}", order['price'], self.net_realized, "SQUAREOFF"), daemon=True).start()
                        except Exception:
                            logger.exception("Notifier send_exit failed during close_all")
            except Exception:
                logger.exception(f"Failed to close position {token}")

    # -------------------------
    # convenience
    # -------------------------
    def reset(self):
        """Clear positions and orders (useful for testing)"""
        with self.order_lock:
            self.positions = {}
            self.orders = []
            self.net_realized = 0.0
            self._save_positions()