# -*- coding: utf-8 -*-
"""
okx_ws_manager.py - High-Performance OKX WebSocket Manager
- Subscribes to Public: books5, trades for target instrument (e.g. SOL-USDT-SWAP)
- Subscribes to Private: orders (real execution fills), account (live equity/margin)
- Computes real-time tick OFI (Order Flow Imbalance) and Micro-Price
- Strictly delivers real execution fills (state == 'filled' / 'partially_filled')
"""

import socket
# Force IPv4 socket resolution globally for OKX requests
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
from typing import Dict, Any, List, Optional
import websockets

class OKXWebSocketManager:
    def __init__(self, api_key: str, api_secret: str, passphrase: str, inst_id: str = "BTC-USDT-SWAP"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.inst_id = inst_id
        
        self.public_uri = "wss://ws.okx.com:443/ws/v5/public"
        self.private_uri = "wss://ws.okx.com:443/ws/v5/private"
        
        self.running = False
        self.lock = threading.Lock()
        
        # Real-time LOB cache
        self.best_bid = 0.0
        self.best_ask = 0.0
        self.best_bid_sz = 0.0
        self.best_ask_sz = 0.0
        self.mid_price = 0.0
        self.micro_price = 0.0
        self.last_book_time = 0.0
        
        # OFI tick state
        self.prev_b1 = 0.0
        self.prev_v_b1 = 0.0
        self.prev_a1 = 0.0
        self.prev_v_a1 = 0.0
        self.ofi_accum = 0.0
        self.recent_ofi_window = []  # (ts, ofi_val)
        
        # Real fill queue
        self.unprocessed_fills: List[Dict[str, Any]] = []
        self.known_fill_ids = set()
        
        # Account cache
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
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main_supervisor())

    async def _main_supervisor(self):
        while self.running:
            try:
                await asyncio.gather(
                    self._run_public_ws(),
                    self._run_private_ws(),
                    return_exceptions=True
                )
            except Exception as e:
                print(f"[WS Supervisor] Gather exception: {e}")
            await asyncio.sleep(2)

    async def _run_public_ws(self):
        while self.running:
            try:
                async with websockets.connect(self.public_uri, ping_interval=20, ping_timeout=10) as ws:
                    sub_msg = {
                        "op": "subscribe",
                        "args": [
                            {"channel": "books5", "instId": self.inst_id},
                            {"channel": "trades", "instId": self.inst_id}
                        ]
                    }
                    await ws.send(json.dumps(sub_msg))
                    while self.running:
                        msg = await ws.recv()
                        self._handle_public_msg(json.loads(msg))
            except Exception as e:
                await asyncio.sleep(2)

    def _handle_public_msg(self, data: Dict[str, Any]):
        arg = data.get("arg", {})
        channel = arg.get("channel")
        if channel == "books5":
            d_list = data.get("data", [])
            if not d_list:
                return
            b = d_list[0]
            bids = b.get("bids", [])
            asks = b.get("asks", [])
            if bids and asks:
                b1 = float(bids[0][0])
                v_b1 = float(bids[0][1])
                a1 = float(asks[0][0])
                v_a1 = float(asks[0][1])
                
                mid = (b1 + a1) * 0.5
                tot_v = v_b1 + v_a1
                micro = (b1 * v_a1 + a1 * v_b1) / tot_v if tot_v > 0 else mid
                
                # Compute Cont-Kukanov-Stoikov OFI
                delta_W_b = 0.0
                if self.prev_b1 > 0:
                    if b1 > self.prev_b1:
                        delta_W_b = v_b1
                    elif b1 == self.prev_b1:
                        delta_W_b = v_b1 - self.prev_v_b1
                    else:
                        delta_W_b = -self.prev_v_b1
                        
                delta_W_a = 0.0
                if self.prev_a1 > 0:
                    if a1 > self.prev_a1:
                        delta_W_a = -v_a1
                    elif a1 == self.prev_a1:
                        delta_W_a = v_a1 - self.prev_v_a1
                    else:
                        delta_W_a = self.prev_v_a1
                        
                tick_ofi = delta_W_b - delta_W_a
                now = time.time()
                
                with self.lock:
                    self.best_bid = b1
                    self.best_bid_sz = v_b1
                    self.best_ask = a1
                    self.best_ask_sz = v_a1
                    self.mid_price = mid
                    self.micro_price = micro
                    self.last_book_time = now
                    
                    self.prev_b1 = b1
                    self.prev_v_b1 = v_b1
                    self.prev_a1 = a1
                    self.prev_v_a1 = v_a1
                    
                    self.recent_ofi_window.append((now, tick_ofi))
                    cutoff = now - 15.0
                    self.recent_ofi_window = [(t, v) for (t, v) in self.recent_ofi_window if t >= cutoff]

    async def _run_private_ws(self):
        while self.running:
            try:
                async with websockets.connect(self.private_uri, ping_interval=20, ping_timeout=10) as ws:
                    ts = str(int(time.time()))
                    sign = base64.b64encode(hmac.new(self.api_secret.encode('utf-8'), f"{ts}GET/users/self/verify".encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
                    login_msg = {
                        "op": "login",
                        "args": [{
                            "apiKey": self.api_key,
                            "passphrase": self.passphrase,
                            "timestamp": ts,
                            "sign": sign
                        }]
                    }
                    await ws.send(json.dumps(login_msg))
                    res_login = json.loads(await ws.recv())
                    if res_login.get("event") == "error":
                        await asyncio.sleep(5)
                        continue
                        
                    sub_msg = {
                        "op": "subscribe",
                        "args": [
                            {"channel": "orders", "instType": "SWAP", "instId": self.inst_id},
                            {"channel": "account"}
                        ]
                    }
                    await ws.send(json.dumps(sub_msg))
                    while self.running:
                        msg = await ws.recv()
                        self._handle_private_msg(json.loads(msg))
            except Exception as e:
                await asyncio.sleep(2)

    def _handle_private_msg(self, data: Dict[str, Any]):
        arg = data.get("arg", {})
        channel = arg.get("channel")
        if channel == "orders":
            orders = data.get("data", [])
            for ord_info in orders:
                state = ord_info.get("state")
                exec_type = ord_info.get("execType", "")
                fill_sz = float(ord_info.get("fillSz", 0))
                
                # Check for REAL execution fills
                if state in ["filled", "partially_filled"] or (exec_type == "T" and fill_sz > 0):
                    fill_id = f"{ord_info.get('ordId')}_{ord_info.get('fillTime', time.time())}_{fill_sz}"
                    with self.lock:
                        if fill_id not in self.known_fill_ids:
                            self.known_fill_ids.add(fill_id)
                            self.unprocessed_fills.append({
                                "ordId": ord_info.get("ordId"),
                                "clOrdId": ord_info.get("clOrdId", ""),
                                "side": ord_info.get("side"),
                                "posSide": ord_info.get("posSide"),
                                "fillPx": float(ord_info.get("fillPx", ord_info.get("px", 0))),
                                "fillSz": fill_sz,
                                "fee": float(ord_info.get("fee", 0)),
                                "feeCcy": ord_info.get("feeCcy", "USDT"),
                                "state": state,
                                "execType": exec_type,
                                "fillTime": ord_info.get("fillTime", int(time.time()*1000))
                            })
        elif channel == "account":
            acc_list = data.get("data", [])
            if acc_list:
                details = acc_list[0].get("details", [])
                for d in details:
                    if d.get("ccy") == "USDT":
                        with self.lock:
                            self.total_equity_usd = float(d.get("eq", 0))
                            self.available_margin_usd = float(d.get("availBal", d.get("cashBal", 0)))

    def get_latest_book(self) -> Dict[str, float]:
        with self.lock:
            return {
                "bid": self.best_bid,
                "ask": self.best_ask,
                "mid": self.mid_price,
                "micro": self.micro_price,
                "time": self.last_book_time
            }

    def get_rolling_ofi(self) -> float:
        with self.lock:
            if not self.recent_ofi_window:
                return 0.0
            return sum(v for (_, v) in self.recent_ofi_window)

    def pop_new_fills(self) -> List[Dict[str, Any]]:
        with self.lock:
            fills = list(self.unprocessed_fills)
            self.unprocessed_fills.clear()
            return fills
