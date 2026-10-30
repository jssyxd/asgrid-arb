# -*- coding: utf-8 -*-
"""
run_doge.py - Production NautilusTrader Live Service for DOGE-USDT (accountbot4)
- Instrument: DOGE-USDT-SWAP (ctVal: 1000 DOGE)
- Capital: 30.0 USDT (3x leverage)
- Architecture: Volume Acceleration Gating (Vol/MA20 > 2.5) + Fat-Tail Spread (12.0 bps)
- Strict Post-Only Maker Execution & Queue Priority Preservation
"""

import socket
# Force IPv4 socket resolution globally for OKX requests
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4_res = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_res if ipv4_res else responses
socket.getaddrinfo = _ipv4_getaddrinfo

import os
import sys
import time
import json
import math
import signal
import numpy as np
import pandas as pd
from datetime import datetime, timezone

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
for cand in [
    os.path.abspath(os.path.join(SERVICE_DIR, "../shared")),
    os.path.abspath(os.path.join(SERVICE_DIR, "../../shared")),
    os.path.abspath(os.path.join(SERVICE_DIR, "..")),
    "/opt/nautilus_cluster/shared"
]:
    if os.path.exists(cand) and cand not in sys.path:
        sys.path.append(cand)

from gateway_okx_client import OKXGatewayClient
from okx_ws_manager import OKXWebSocketManager

CONFIG_FILE = os.path.join(SERVICE_DIR, "config/accountbot4_credentials.env")
LOG_DIR = os.path.join(SERVICE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "02_doge_status.json")
FILLS_FILE = os.path.join(LOG_DIR, "02_doge_fills.json")
LOG_FILE = os.path.join(LOG_DIR, "02_doge_runtime.log")

os.makedirs(LOG_DIR, exist_ok=True)

def load_credentials():
    creds = {
        "OKX_API_KEY": os.environ.get("OKX_API_KEY", ""),
        "OKX_API_SECRET": os.environ.get("OKX_API_SECRET", ""),
        "OKX_API_PASSPHRASE": os.environ.get("OKX_API_PASSPHRASE", ""),
        "OKX_SIMULATED_TRADING": os.environ.get("OKX_SIMULATED_TRADING", "0"),
        "ACCOUNT_LABEL": os.environ.get("ACCOUNT_LABEL", "accountbot4"),
        "INST_ID": os.environ.get("INST_ID", "DOGE-USDT-SWAP"),
        "INITIAL_CAPITAL": os.environ.get("INITIAL_CAPITAL", "30.0"),
        "LOT_SZ": os.environ.get("LOT_SZ", "0.10"),
        "MAX_INVENTORY": os.environ.get("MAX_INVENTORY", "0.40"),
        "MIN_SPREAD_BPS": os.environ.get("MIN_SPREAD_BPS", "12.0"),
        "PRICE_TOLERANCE": os.environ.get("PRICE_TOLERANCE", "0.00005"),
        "VOL_ACCEL_THRESH": os.environ.get("VOL_ACCEL_THRESH", "2.5"),
        "GAMMA": os.environ.get("GAMMA", "0.35"),
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds

def log_msg(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [02_DOGE_accountbot4] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

running = True
def handle_shutdown(signum, frame):
    global running
    log_msg("Received shutdown signal. Stopping gracefully...")
    running = False

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

def compute_doge_micro_features(candles):
    arr = np.array(candles, dtype=object)[::-1]
    open_ = arr[:, 1].astype(float)
    high = arr[:, 2].astype(float)
    low = arr[:, 3].astype(float)
    close = arr[:, 4].astype(float)
    vol = arr[:, 5].astype(float)
    
    cur_c = close[-1]
    cur_v = vol[-1]
    ma20_v = np.mean(vol[-20:]) if len(vol) >= 20 else cur_v
    vol_accel = cur_v / (ma20_v + 1e-6)
    
    log_hl = np.log(np.maximum(high, 1e-6) / np.maximum(low, 1e-6))
    log_co = np.log(np.maximum(close, 1e-6) / np.maximum(open_, 1e-6))
    gk_var = 0.5 * (log_hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (log_co ** 2)
    annual_gk = np.sqrt(np.maximum(np.mean(gk_var[-20:]), 1e-9) * (365.25 * 1440))
    
    # 1-bar price direction for volume acceleration gating
    ret1 = (cur_c - close[-2]) / close[-2] if len(close) >= 2 else 0.0
    
    return float(vol_accel), float(annual_gk), float(cur_c), float(ret1)

def main():
    log_msg("=== Starting NautilusTrader DOGE-USDT (accountbot4) Production Live Service ===")
    creds = load_credentials()
    simulated = (creds.get("OKX_SIMULATED_TRADING", "0") == "1")
    inst_id = creds.get("INST_ID", "DOGE-USDT-SWAP")
    
    client = OKXGatewayClient(
        api_key=creds["OKX_API_KEY"],
        api_secret=creds["OKX_API_SECRET"],
        passphrase=creds["OKX_API_PASSPHRASE"],
        simulated=simulated
    )
    
    bal = client.get_balance("USDT")
    avail_bal = float(bal.get("availBal", bal.get("cashBal", 0)))
    log_msg(f"Connected to OKX {'Demo' if simulated else 'Real'}. Available Capital: {avail_bal} USDT")
    
    ws_mgr = OKXWebSocketManager(
        api_key=creds["OKX_API_KEY"],
        api_secret=creds["OKX_API_SECRET"],
        passphrase=creds["OKX_API_PASSPHRASE"],
        inst_id=inst_id
    )
    log_msg(f"Starting OKX WebSocket streams for {inst_id}...")
    ws_mgr.start()
    
    lot_sz = creds.get("LOT_SZ", "0.10")  # 0.10 contract = 100 DOGE
    max_inv = float(creds.get("MAX_INVENTORY", 0.40)) # 0.40 contract = 400 DOGE
    min_spread_bps = float(creds.get("MIN_SPREAD_BPS", 12.0))
    price_tol = float(creds.get("PRICE_TOLERANCE", 0.00005))
    gamma = float(creds.get("GAMMA", 0.35))
    vol_accel_thresh = float(creds.get("VOL_ACCEL_THRESH", 2.5))
    
    inventory = 0.0
    init_positions = client.get_positions(inst_type="SWAP", inst_id=inst_id)
    if init_positions:
        inventory = float(init_positions[0].get("pos", 0))
        log_msg(f"Synced initial live position: {inventory} contracts")
        
    loop_count = 0
    last_candle_fetch = 0.0
    cached_vol_accel = 1.0
    cached_gk = 0.80
    cached_ret1 = 0.0
    
    last_fill_time_bid = 0.0
    last_fill_time_ask = 0.0
    FILL_COOLDOWN_SEC = 5.0
    last_pos = inventory
    
    real_matched = 0
    real_volume = 0.0
    
    time.sleep(2)
    
    while running:
        loop_count += 1
        t_start = time.time()
        try:
            # 1. Process real fills from WebSocket
            new_fills = ws_mgr.pop_new_fills()
            for f in new_fills:
                real_matched += 1
                notional = float(f['fillSz']) * 1000.0 * float(f['fillPx'])
                real_volume += notional
                log_msg(f"⭐ [REAL FILL] {f['side']} {f['fillSz']} contracts @ {f['fillPx']} | Fee: {f['fee']} {f['feeCcy']}")
                
            if inventory > last_pos:
                last_fill_time_bid = time.time()
                log_msg(f"⚡ Buy Fill detected ({last_pos} -> {inventory}), cooldown 5s")
            elif inventory < last_pos:
                last_fill_time_ask = time.time()
                log_msg(f"⚡ Sell Fill detected ({last_pos} -> {inventory}), cooldown 5s")
            last_pos = inventory
            
            cd_bid = (time.time() - last_fill_time_bid) < FILL_COOLDOWN_SEC
            cd_ask = (time.time() - last_fill_time_ask) < FILL_COOLDOWN_SEC
            
            # 2. Update K-lines every 15s
            if time.time() - last_candle_fetch >= 15.0:
                candles = client.get_candles(inst_id, bar="1m", limit=30)
                if candles:
                    cached_vol_accel, cached_gk, _, cached_ret1 = compute_doge_micro_features(candles)
                    last_candle_fetch = time.time()
                    
            # 3. Retrieve orderbook from WS
            book = ws_mgr.get_latest_book()
            mid_px = book["mid"]
            if mid_px <= 0:
                t_data = client.get_ticker(inst_id)
                mid_px = float(t_data.get("last", 0.075))
            micro_px = book["micro"] if book["micro"] > 0 else mid_px
            
            # 4. DOGE Pricing Engine with Volume Acceleration Gating
            base_half_spd = max(mid_px * (min_spread_bps * 0.5 / 10000.0), (1.0 / gamma) * math.log(1.0 + gamma / 2.1346) * (mid_px * 0.0004))
            
            inv_ratio = np.clip(inventory / max(max_inv, 1e-6), -1.0, 1.0)
            inv_bias = inv_ratio * base_half_spd * 0.75
            
            r = micro_px - inv_bias
            
            calc_bid = round(r - (base_half_spd + inv_bias), 5)
            calc_ask = round(r + (base_half_spd - inv_bias), 5)
            
            # Strict Post-Only clamp
            calc_bid = min(calc_bid, round(mid_px - base_half_spd * 0.5, 5))
            calc_ask = max(calc_ask, round(mid_px + base_half_spd * 0.5, 5))
            
            allow_bid = (inventory < max_inv) and not cd_bid
            allow_ask = (inventory > -max_inv) and not cd_ask
            
            # Volume Acceleration Gating Model: If volume explodes > thresh, cut counter-trend quotes
            if cached_vol_accel > vol_accel_thresh:
                if cached_ret1 > 0:
                    allow_ask = False # Bullish surge: cut asks to avoid getting steamrolled
                elif cached_ret1 < 0:
                    allow_bid = False # Panic dump: cut bids to avoid catching falling knives
                    
            # 5. Order Management with Queue Priority Hold
            pending = client.get_pending_orders(inst_type="SWAP", inst_id=inst_id)
            exist_buy = None
            exist_sell = None
            cancel_list = []
            
            for p in pending:
                side_p = p.get("side", "").lower()
                px_p = float(p.get("px", 0))
                ord_id = p.get("ordId")
                
                if side_p == "buy":
                    if allow_bid and abs(px_p - calc_bid) <= price_tol:
                        exist_buy = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})
                elif side_p == "sell":
                    if allow_ask and abs(px_p - calc_ask) <= price_tol:
                        exist_sell = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})
                        
            if cancel_list:
                try:
                    client.cancel_batch_orders(cancel_list)
                except Exception:
                    pass
                    
            actions = []
            now_ms = int(time.time() * 1000)
            
            if allow_bid:
                if exist_buy:
                    actions.append(f"BID_HOLD({exist_buy.get('px')})")
                else:
                    cl_id = f"asb{now_ms}"[-32:]
                    res = client.place_order(inst_id, "cross", "buy", "post_only", str(calc_bid), lot_sz, cl_id)
                    actions.append(f"BID_POST({calc_bid})" if res.get("code") == "0" else f"BID_REJ({res.get('msg')})")
            else:
                actions.append("BID_CUT")
                
            if allow_ask:
                if exist_sell:
                    actions.append(f"ASK_HOLD({exist_sell.get('px')})")
                else:
                    cl_id = f"asa{now_ms}"[-32:]
                    res = client.place_order(inst_id, "cross", "sell", "post_only", str(calc_ask), lot_sz, cl_id)
                    actions.append(f"ASK_POST({calc_ask})" if res.get("code") == "0" else f"ASK_REJ({res.get('msg')})")
            else:
                actions.append("ASK_CUT")
                
            if loop_count % 10 == 0:
                pos_list = client.get_positions(inst_type="SWAP", inst_id=inst_id)
                if pos_list:
                    inventory = float(pos_list[0].get("pos", 0))
                    
            if loop_count % 5 == 0:
                log_msg(f"Heartbeat #{loop_count}: Mid={mid_px:.5f}, Inv={inventory}, VolAccel={cached_vol_accel:.2f}, Fills={real_matched}, Actions={' | '.join(actions)}")
                
            status_data = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": inst_id,
                "mid_price": mid_px,
                "micro_price": micro_px,
                "inventory": inventory,
                "max_inventory": max_inv,
                "vol_accel": cached_vol_accel,
                "real_matched": real_matched,
                "actions": actions
            }
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
                
        except Exception as e:
            log_msg(f"Exception in loop: {e}")
            
        t_elapsed = time.time() - t_start
        time.sleep(max(0.1, 1.0 - t_elapsed))
        
    ws_mgr.stop()
    log_msg("DOGE Live Service stopped cleanly.")

if __name__ == "__main__":
    main()
