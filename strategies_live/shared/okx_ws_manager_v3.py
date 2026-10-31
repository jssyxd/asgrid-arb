# -*- coding: utf-8 -*-
"""
okx_ws_manager.py - Pure Event-Driven OKX WebSocket Manager (v3)
- Public: books5, trades
- Business: candle1m  (eliminates all REST candle polling)
- Private: orders (real execution fills), account
- tick_event: threading.Event set on every market update so the strategy
  loop wakes immediately instead of sleeping on a fixed interval.
"""

import socket
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4_res = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_res if ipv4_res else responses
socket.getaddrinfo = _ipv4_getaddrinfo

import asyncio
import time
import json
import hmac
import hashlib
import base64
import threading
from typing import Dict, Any, List
import websockets

class OKXWebSocketManager:
    def __init__(self, api_key: str, api_secret: str, passphrase: str,
                 inst_id: str = "BTC-USDT-SWAP"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.inst_id = inst_id

        self.public_uri = "wss://ws.okx.com:443/ws/v5/public"
        self.business_uri = "wss://ws.okx.com:443/ws/v5/business"
        self.private_uri = "wss://ws.okx.com:443/ws/v5/private"

        self.running = False
        self.lock = threading.Lock()
        self.tick_event = threading.Event()

        # L2 cache
        self.best_bid = 0.0
        self.best_ask = 0.0
        self.best_bid_sz = 0.0
        self.best_ask_sz = 0.0
        self.mid_price = 0.0
        self.micro_price = 0.0
        self.last_book_time = 0.0

        # OFI
        self.prev_b1 = 0.0
        self.prev_v_b1 = 0.0
        self.prev_a1 = 0.0
        self.prev_v_a1 = 0.0
        self.recent_ofi_window = []

        # Streaming 1m candles, keyed by bar-open ms
        self.candles_1m = {}

        # Real fills
        self.unprocessed_fills: List[Dict[str, Any]] = []
        self.known_fill_ids = set()

        # Account
        self.total_equity_usd = 0.0
        self.available_margin_usd = 0.0

        self.loop = None
        self.ws_thread = None

    def start(self):
        self.running = True
        self.ws_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.ws_thread.start()

    def stop(self):
        self.running = False
        self.tick_event.set()
        if self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main_supervisor())

    async def _main_supervisor(self):
        while self.running:
            try:
                await asyncio.gather(
                    self._run_public_ws(),
                    self._run_business_ws(),
                    self._run_private_ws(),
                    return_exceptions=True
                )
            except Exception as e:
                print(f"[WS Supervisor] {e}", flush=True)
            await asyncio.sleep(2)

    async def _run_public_ws(self):
        while self.running:
            try:
                async with websockets.connect(self.public_uri, ping_interval=20, ping_timeout=10) as ws:
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [
                            {"channel": "books5", "instId": self.inst_id},
                            {"channel": "trades", "instId": self.inst_id},
                        ]
                    }))
                    while self.running:
                        msg = await ws.recv()
                        self._handle_public_msg(json.loads(msg))
            except Exception:
                await asyncio.sleep(2)

    async def _run_business_ws(self):
        """Streaming 1m candles; replaces REST get_candles entirely."""
        while self.running:
            try:
                async with websockets.connect(self.business_uri, ping_interval=20, ping_timeout=10) as ws:
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [{"channel": "candle1m", "instId": self.inst_id}]
                    }))
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("arg", {}).get("channel") == "candle1m":
                            self._handle_candles(data.get("data", []))
            except Exception:
                await asyncio.sleep(2)

    def _handle_candles(self, rows):
        if not rows:
            return
        with self.lock:
            for r in rows:
                ts = int(r[0])
                self.candles_1m[ts] = [ts, float(r[1]), float(r[2]),
                                       float(r[3]), float(r[4]), float(r[5])]
            if len(self.candles_1m) > 120:
                for k in sorted(self.candles_1m)[:-120]:
                    self.candles_1m.pop(k, None)
        self.tick_event.set()

    def _handle_public_msg(self, data):
        channel = data.get("arg", {}).get("channel")
        if channel != "books5":
            return
        d_list = data.get("data", [])
        if not d_list:
            return
        b = d_list[0]
        bids, asks = b.get("bids", []), b.get("asks", [])
        if not bids or not asks:
            return

        b1 = float(bids[0][0]); v_b1 = float(bids[0][1])
        a1 = float(asks[0][0]); v_a1 = float(asks[0][1])
        mid = (b1 + a1) * 0.5
        tot = v_b1 + v_a1
        micro = (b1 * v_a1 + a1 * v_b1) / tot if tot > 0 else mid

        dWb = 0.0
        if self.prev_b1 > 0:
            if b1 > self.prev_b1:
                dWb = v_b1
            elif b1 == self.prev_b1:
                dWb = v_b1 - self.prev_v_b1
            else:
                dWb = -self.prev_v_b1
        dWa = 0.0
        if self.prev_a1 > 0:
            if a1 > self.prev_a1:
                dWa = -v_a1
            elif a1 == self.prev_a1:
                dWa = v_a1 - self.prev_v_a1
            else:
                dWa = self.prev_v_a1
        tick_ofi = dWb - dWa
        now = time.time()

        with self.lock:
            self.best_bid = b1; self.best_bid_sz = v_b1
            self.best_ask = a1; self.best_ask_sz = v_a1
            self.mid_price = mid; self.micro_price = micro
            self.last_book_time = now
            self.prev_b1 = b1; self.prev_v_b1 = v_b1
            self.prev_a1 = a1; self.prev_v_a1 = v_a1
            self.recent_ofi_window.append((now, tick_ofi))
            cutoff = now - 15.0
            self.recent_ofi_window = [(t, v) for (t, v) in self.recent_ofi_window if t >= cutoff]
        self.tick_event.set()

    async def _run_private_ws(self):
        while self.running:
            try:
                async with websockets.connect(self.private_uri, ping_interval=20, ping_timeout=10) as ws:
                    ts = str(int(time.time()))
                    sign = base64.b64encode(hmac.new(
                        self.api_secret.encode(), f"{ts}GET/users/self/verify".encode(),
                        hashlib.sha256).digest()).decode()
                    await ws.send(json.dumps({
                        "op": "login",
                        "args": [{"apiKey": self.api_key, "passphrase": self.passphrase,
                                  "timestamp": ts, "sign": sign}]
                    }))
                    res_login = json.loads(await ws.recv())
                    if res_login.get("event") == "error":
                        await asyncio.sleep(5)
                        continue

                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [
                            {"channel": "orders", "instType": "SWAP", "instId": self.inst_id},
                            {"channel": "account"},
                        ]
                    }))
                    while self.running:
                        msg = await ws.recv()
                        self._handle_private_msg(json.loads(msg))
            except Exception:
                await asyncio.sleep(2)

    def _handle_private_msg(self, data):
        channel = data.get("arg", {}).get("channel")
        if channel == "orders":
            for o in data.get("data", []):
                state = o.get("state")
                exec_type = o.get("execType", "")
                fill_sz = float(o.get("fillSz", 0))
                if state in ("filled", "partially_filled") or (exec_type == "T" and fill_sz > 0):
                    fid = f"{o.get('ordId')}_{o.get('fillTime', time.time())}_{fill_sz}"
                    with self.lock:
                        if fid not in self.known_fill_ids:
                            self.known_fill_ids.add(fid)
                            self.unprocessed_fills.append({
                                "ordId": o.get("ordId"),
                                "clOrdId": o.get("clOrdId", ""),
                                "side": o.get("side"),
                                "posSide": o.get("posSide"),
                                "fillPx": float(o.get("fillPx", o.get("px", 0))),
                                "fillSz": fill_sz,
                                "fee": float(o.get("fee", 0)),
                                "feeCcy": o.get("feeCcy", "USDT"),
                                "state": state,
                                "execType": exec_type,
                                "fillTime": o.get("fillTime", int(time.time() * 1000)),
                            })
                    self.tick_event.set()
        elif channel == "account":
            acc = data.get("data", [])
            if acc:
                for d in acc[0].get("details", []):
                    if d.get("ccy") == "USDT":
                        with self.lock:
                            self.total_equity_usd = float(d.get("eq", 0))
                            self.available_margin_usd = float(d.get("availBal", d.get("cashBal", 0)))

    def get_latest_book(self) -> Dict[str, float]:
        with self.lock:
            return {"bid": self.best_bid, "ask": self.best_ask, "mid": self.mid_price,
                    "micro": self.micro_price, "time": self.last_book_time}

    def get_rolling_ofi(self) -> float:
        with self.lock:
            return sum(v for (_, v) in self.recent_ofi_window) if self.recent_ofi_window else 0.0

    def get_streaming_candles(self) -> List[List[float]]:
        with self.lock:
            return [self.candles_1m[k] for k in sorted(self.candles_1m)]

    def pop_new_fills(self) -> List[Dict[str, Any]]:
        with self.lock:
            fills = list(self.unprocessed_fills)
            self.unprocessed_fills.clear()
            return fills
