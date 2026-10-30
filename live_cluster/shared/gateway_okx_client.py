# -*- coding: utf-8 -*-
"""
gateway_okx_client.py - Production OKX Gateway Client
- Global IPv4 socket resolution (avoids IPv6 DNS delay and OKX 50110 errors)
- Chrome User-Agent header (prevents Cloudflare 403 blocks)
- HMAC-SHA256 signature authentication
- Supports batch orders, positions, balances, and orders channel
"""

import socket
# Force IPv4 socket resolution globally
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4_res = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_res if ipv4_res else responses
socket.getaddrinfo = _ipv4_getaddrinfo

import os
import time
import json
import hmac
import hashlib
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

class OKXGatewayClient:
    def __init__(self, api_key: str, api_secret: str, passphrase: str, simulated: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.simulated = simulated
        self.base_url = "https://www.okx.com"

    def _sign_and_request(self, method: str, endpoint: str, params: Optional[Dict] = None, body: Optional[Dict] = None) -> Dict[str, Any]:
        request_path = endpoint
        if params:
            query_str = urllib.parse.urlencode(params)
            request_path = f"{endpoint}?{query_str}"
        url = f"{self.base_url}{request_path}"

        ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
        body_str = json.dumps(body) if body else ""
        msg = f"{ts}{method}{request_path}{body_str}"
        sig = base64.b64encode(hmac.new(self.api_secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': sig,
            'OK-ACCESS-TIMESTAMP': ts,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
        }
        if self.simulated:
            headers['x-simulated-trading'] = '1'

        data_bytes = body_str.encode('utf-8') if body else None
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                res_body = response.read().decode('utf-8')
                return json.loads(res_body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8') if e.fp else ""
            return {"code": str(e.code), "msg": f"HTTP Error {e.code}: {err_body}", "data": []}
        except Exception as e:
            return {"code": "-1", "msg": str(e), "data": []}

    def get_ticker(self, inst_id: str) -> Dict[str, Any]:
        res = self._sign_and_request('GET', '/api/v5/market/ticker', {'instId': inst_id})
        data = res.get('data', [])
        return data[0] if data else {}

    def get_books(self, inst_id: str, sz: int = 20) -> Dict[str, Any]:
        res = self._sign_and_request('GET', '/api/v5/market/books', {'instId': inst_id, 'sz': str(sz)})
        data = res.get('data', [])
        return data[0] if data else {}

    def get_candles(self, inst_id: str, bar: str = '1m', limit: int = 30) -> List[List[str]]:
        res = self._sign_and_request('GET', '/api/v5/market/candles', {'instId': inst_id, 'bar': bar, 'limit': str(limit)})
        return res.get('data', [])

    def get_balance(self, ccy: str = 'USDT') -> Dict[str, Any]:
        res = self._sign_and_request('GET', '/api/v5/account/balance', {'ccy': ccy})
        data = res.get('data', [])
        if data and 'details' in data[0] and data[0]['details']:
            return data[0]['details'][0]
        return {}

    def get_positions(self, inst_type: str = 'SWAP', inst_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {'instType': inst_type}
        if inst_id:
            params['instId'] = inst_id
        res = self._sign_and_request('GET', '/api/v5/account/positions', params)
        return res.get('data', [])

    def get_funding_rate(self, inst_id: str) -> Dict[str, Any]:
        res = self._sign_and_request('GET', '/api/v5/public/funding-rate', {'instId': inst_id})
        data = res.get('data', [])
        return data[0] if data else {}

    def get_pending_orders(self, inst_type: str = 'SWAP', inst_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {'instType': inst_type}
        if inst_id:
            params['instId'] = inst_id
        res = self._sign_and_request('GET', '/api/v5/trade/orders-pending', params)
        return res.get('data', [])

    def place_order(self, inst_id: str, td_mode: str, side: str, ord_type: str, px: str, sz: str, cl_ord_id: Optional[str] = None) -> Dict[str, Any]:
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "px": px,
            "sz": sz
        }
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        return self._sign_and_request('POST', '/api/v5/trade/order', body=body)

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        body = {"instId": inst_id, "ordId": ord_id}
        return self._sign_and_request('POST', '/api/v5/trade/cancel-order', body=body)

    def cancel_batch_orders(self, orders: List[Dict[str, str]]) -> Dict[str, Any]:
        if not orders:
            return {"code": "0", "msg": "No orders to cancel"}
        return self._sign_and_request('POST', '/api/v5/trade/cancel-batch-orders', body=orders)
